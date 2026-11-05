import { createContext, useContext, useEffect, useRef, useState, type ComponentProps, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import {
  AssistantRuntimeProvider,
  AuiConfig,
  defineToolkit,
  Tools,
  unstable_createMessageConverter,
  useAssistantTransportRuntime,
  useAuiState,
  type AssistantTransportConnectionMetadata,
  type ToolCallMessagePartProps,
} from '@assistant-ui/react'
import { convertLangChainMessages, type LangChainMessage } from '@assistant-ui/react-langgraph'
import { BookOpenIcon, PlusIcon, SearchIcon } from 'lucide-react'
import { api, pageUrl } from '@/api'
import { MarkdownText } from '@/components/assistant-ui/elements/markdown-text'
import { Thread } from '@/components/assistant-ui/elements/thread.aui'
import { CitationChip } from '@/components/citation'
import { PageViewer, type ViewerPage } from '@/components/page-viewer'
import { Warning } from '@/components/warning'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { displayTitle, plural, useLibrary } from '@/lib/library'
import { useTitle } from '@/lib/hooks'

// The agent's state as the server streams it (app/backend/rag/agent.py): LangChain messages.
type State = { messages: LangChainMessage[] }

const LAST = 'grirag.research' // the conversation the Research link reopens
const newThreadId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8)

// "/research?t=…": a conversation with the research agent, saved on the server and reopened by its id.
export function ResearchPage() {
  const { t, q } = useSearch({ from: '/research' })
  const navigate = useNavigate({ from: '/research' })
  useTitle('Research')
  useEffect(() => {
    if (t) localStorage.setItem(LAST, t)
    else navigate({ search: { t: (!q && localStorage.getItem(LAST)) || newThreadId(), q }, replace: true })
  }, [t, q, navigate])
  // Fetched on every visit (gcTime 0): the server's copy is the conversation.
  const saved = useQuery({
    queryKey: ['conversation', t],
    queryFn: () => api.conversation<LangChainMessage>(t!),
    enabled: !!t,
    gcTime: 0,
  })

  return (
    <div className="mx-auto flex h-[calc(100dvh-6.5rem)] max-w-3xl flex-col gap-3">
      {saved.error ? (
        <>
          <Header>
            <NewConversation />
          </Header>
          <Warning error>Can't load this conversation ({saved.error.message}).</Warning>
        </>
      ) : saved.data && t ? (
        <Conversation key={t} threadId={t} saved={saved.data} question={q} />
      ) : (
        <>
          <Header>
            <NewConversation disabled />
          </Header>
          {/* Shown only if loading takes a while: a fetch of a few ms would flash it. */}
          <div className="animate-in fade-in fill-mode-both space-y-3 pt-6 duration-200 [animation-delay:300ms]">
            <Skeleton className="ml-auto h-9 w-2/5" />
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-3/5" />
          </div>
        </>
      )}
    </div>
  )
}

function Header({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <h1 className="font-heading text-lg font-semibold tracking-[-0.01em]">Research</h1>
      {children}
    </div>
  )
}

function NewConversation({ disabled }: { disabled?: boolean }) {
  const navigate = useNavigate({ from: '/research' })
  return (
    // Off but not faded: the button just does nothing until there is something to leave.
    <Button
      variant="outline"
      size="sm"
      disabled={disabled}
      className="disabled:opacity-100"
      onClick={() => navigate({ search: { t: newThreadId() } })}
    >
      <PlusIcon /> New conversation
    </Button>
  )
}

// Off until something has been asked: a conversation with no messages is already a new one.
function NewConversationOnceAsked() {
  const empty = useAuiState((s) => s.thread.messages.length === 0)
  return <NewConversation disabled={empty} />
}

const messages = unstable_createMessageConverter(convertLangChainMessages)

// Questions not yet answered by the server show right away.
function converter(state: State, { pendingCommands, isSending }: AssistantTransportConnectionMetadata) {
  const pending = pendingCommands.flatMap((c): LangChainMessage[] =>
    c.type === 'add-message' && c.message.role === 'user'
      ? [{ type: 'human', id: c.message.id, content: c.message.parts.map((p) => ('text' in p ? p.text : '')).join(' ') }]
      : [],
  )
  return { messages: messages.toThreadMessages([...state.messages, ...pending], isSending), isRunning: isSending }
}

const OpenPage = createContext<(p: ViewerPage) => void>(() => {})

const toolkit = defineToolkit({
  search_pages: { type: 'backend', render: SearchedLine },
  read_pages: { type: 'backend', render: ReadPages },
})

type Props = { threadId: string; saved: State; question?: string }

function Conversation({ threadId, saved, question }: Props) {
  const navigate = useNavigate({ from: '/research' })
  const [viewer, setViewer] = useState<ViewerPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const runtime = useAssistantTransportRuntime<State>({
    api: '/api/agent',
    protocol: 'assistant-transport', // AssistantTransportResponse on the server
    initialState: saved,
    headers: {},
    body: { thread_id: threadId },
    converter,
    onResponse: () => setError(null),
    onError: (e) => setError(e.message),
  })
  const config = AuiConfig({ tools: Tools({ toolkit }) })

  // A question brought from the Ask box starts a new conversation, once.
  const sent = useRef(false)
  useEffect(() => {
    if (!question || sent.current) return
    sent.current = true
    if (!saved.messages.length) runtime.thread.append(question)
    navigate({ search: { t: threadId }, replace: true })
  }, [question, saved, runtime, navigate, threadId])

  return (
    <OpenPage value={setViewer}>
      <AssistantRuntimeProvider runtime={runtime} config={config}>
        <Header>
          <NewConversationOnceAsked />
        </Header>
        <div className="min-h-0 flex-1">
          <Thread components={{ Welcome, Text: CitedText, ToolGroup }} />
        </div>
      </AssistantRuntimeProvider>
      {error && (
        <Warning error role="status">
          {error}
        </Warning>
      )}
      <PageViewer page={viewer} onChange={setViewer} />
    </OpenPage>
  )
}

function Welcome() {
  return (
    <div className="mb-6 space-y-2 px-2">
      <p className="font-heading text-[1.75rem] leading-tight font-bold tracking-[-0.025em]">Research your documents</p>
      <p className="max-w-[58ch] text-pretty text-muted-foreground">
        For harder questions, like comparing documents or collecting facts spread across many pages. A deep agent
        digs through your documents for you.
      </p>
    </div>
  )
}

// Tool calls show as plain lines, never folded away.
function ToolGroup({ children }: { children?: ReactNode }) {
  return <div className="my-2 space-y-2">{children}</div>
}

// ---------------------------------------------------------------- citations: [#120003] → S1, opening that page

// [#120003], [#120003, #20001] and [#120003][#20001] become links #page-<id>, labelled S1, S2… in the order the
// text first cites them. A page's id is doc_id * 10000 + page (the Qdrant point id).
const pageCitations = /\[(#\d+(?:\s*,\s*#\d+)*)\]/g
function linkPageCitations(text: string) {
  const order: string[] = []
  return text.replace(/<think>[\s\S]*?(<\/think>|$)/g, '').replace(pageCitations, (_, ids: string) =>
    ids
      .split(/\s*,\s*/)
      .map((id) => `[S${order.indexOf(id) + 1 || order.push(id)}](#page-${id.slice(1)})`)
      .join(' '),
  )
}

const toPage = (id: number) => ({ docId: Math.floor(id / 10000), page: id % 10000 })

function CitedText() {
  return <MarkdownText preprocess={linkPageCitations} components={{ a: CitationLink }} />
}

function CitationLink({ href, children, ...props }: ComponentProps<'a'>) {
  const open = useContext(OpenPage)
  const docs = useLibrary().data?.docs
  const id = Number(href?.match(/^#page-(\d+)$/)?.[1])
  if (!id)
    return (
      <a href={href} target="_blank" rel="noreferrer" className="underline" {...props}>
        {children}
      </a>
    )
  const { docId, page } = toPage(id)
  const doc = docs?.find((d) => d.id === docId)
  return (
    <CitationChip
      title={`${doc ? displayTitle(doc) : `Document ${docId}`}, page ${page}`}
      onClick={() => open({ docId, page, label: String(children) })}
    >
      {children}
    </CitationChip>
  )
}

// ---------------------------------------------------------------- tool calls

const toolLine = 'flex items-center gap-2 text-sm text-muted-foreground [&>svg]:size-4 [&>svg]:shrink-0'

// "Searched: invoice total · 12 pages"
function SearchedLine({ args, result }: ToolCallMessagePartProps<{ query?: string }, string>) {
  const found = typeof result === 'string' ? result.split('\n').filter((l) => l.startsWith('#')).length : null
  return (
    <p className={toolLine}>
      {result === undefined ? <Spinner /> : <SearchIcon />}
      <span className="min-w-0 truncate">
        Searched: <span className="text-foreground">{args.query}</span>
        {found !== null && ` · ${found ? plural(found, 'page') : result}`}
      </span>
    </p>
  )
}

// "Read 3 pages" with the pages as small thumbnails.
function ReadPages({ args, result }: ToolCallMessagePartProps<{ ids?: number[] }, string>) {
  const open = useContext(OpenPage)
  const ids = args.ids ?? []
  return (
    <div className="space-y-2">
      <p className={toolLine}>
        {result === undefined ? <Spinner /> : <BookOpenIcon />}
        {result === undefined ? 'Reading' : 'Read'} {plural(ids.length, 'page')}
      </p>
      <div className="flex flex-wrap gap-2">
        {ids.map((id) => {
          const { docId, page } = toPage(id)
          return (
            <button
              key={id}
              type="button"
              aria-label={`Open page ${page} of document ${docId}`}
              onClick={() => open({ docId, page })}
              className="rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <img
                src={pageUrl(docId, page)}
                alt=""
                loading="lazy"
                className="aspect-[3/4] w-12 rounded-sm border bg-white object-contain object-top transition-shadow hover:ring-2 hover:ring-highlight"
              />
            </button>
          )
        })}
      </div>
    </div>
  )
}
