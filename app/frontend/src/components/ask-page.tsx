import { useRef, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { ArrowRightIcon, MessagesSquareIcon, RotateCwIcon, SparklesIcon } from 'lucide-react'
import { api, type AskResult } from '@/api'
import { AddPanel } from '@/components/add-panel'
import { AnswerView } from '@/components/answer-view'
import { LightTable } from '@/components/light-table'
import { PageViewer, type ViewerPage } from '@/components/page-viewer'
import { SearchResults } from '@/components/search-results'
import { Warning } from '@/components/warning'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { isProcessing, useLibrary } from '@/lib/library'
import { useSlashFocus, useTitle } from '@/lib/hooks'
import { cn } from '@/lib/utils'

// "/": ask. The question is in the URL (?q=…), so Back/Forward work; answers stay cached for the session, so
// coming back from a document does not ask again.
export function AskPage() {
  const { q } = useSearch({ from: '/' })
  const library = useLibrary()
  const quota = useQuery({ queryKey: ['quota'], queryFn: api.quota })
  useTitle(q || 'Ask')
  if (q) return <Results key={q} q={q} quota={quota.data?.quota} />
  if (library.isSuccess && !library.data.docs.length) return <FirstRun />
  const docs = library.data?.docs ?? []
  const processing = docs.filter(isProcessing).length
  return (
    <div className="mx-auto max-w-3xl space-y-16 pt-[8vh] pb-8">
      <div className="space-y-6">
        <div className="space-y-3">
          <h1 className="font-heading text-[clamp(2rem,6vw,2.875rem)] leading-[1.08] font-bold tracking-[-0.03em] text-balance">
            Ask your documents
          </h1>
          <p className="max-w-[58ch] text-pretty text-muted-foreground">
            Ask a quick question about your docs, or have a conversation with a deep agent in Research mode. Every
            answer is based on your documents and links to the pages it comes from.
          </p>
        </div>
        <AskForm />
        {quota.data?.quota && <p className="text-xs text-muted-foreground">{quota.data.quota}</p>}
      </div>
      {docs.length > 0 && <LightTable docs={docs} processing={processing} />}
    </div>
  )
}

function FirstRun() {
  return (
    <div className="mx-auto max-w-xl space-y-6 pt-[8vh]">
      <div className="space-y-2 text-center">
        <h1 className="font-heading text-[2rem] leading-tight font-bold tracking-[-0.025em]">Welcome to GriRAG</h1>
        <p className="text-balance text-muted-foreground">
          Add PDFs, Word files or web links. Every page becomes an image you can search, and questions are answered
          from the best pages, with the sources cited.
        </p>
      </div>
      <Card>
        <CardContent>
          <AddPanel />
        </CardContent>
      </Card>
    </div>
  )
}

const modeItem =
  'h-full rounded-md px-3 text-muted-foreground hover:text-foreground data-[state=on]:bg-card data-[state=on]:text-foreground data-[state=on]:shadow-sm max-sm:flex-1'

function AskForm({ q = '' }: { q?: string }) {
  const navigate = useNavigate({ from: '/' })
  const queryClient = useQueryClient()
  const [text, setText] = useState(q)
  const input = useRef<HTMLInputElement>(null)

  useSlashFocus(input)

  function submit(e: FormEvent) {
    e.preventDefault()
    const next = text.trim()
    if (!next) return
    // Submitting a question (again) is an explicit request for a fresh answer; Back/Forward reuse the cache.
    if (next === q) {
      queryClient.refetchQueries({ queryKey: ['ask', q] }, { cancelRefetch: false })
    } else {
      queryClient.removeQueries({ queryKey: ['ask', next], exact: true })
      navigate({ search: { q: next } })
    }
  }

  return (
    // One field: the box, the mode and the button share a border, and the focus ring goes around all of them.
    <form
      onSubmit={submit}
      className="flex flex-wrap items-center gap-1.5 rounded-xl border border-input bg-card p-1.5 shadow-sm transition-[border-color,box-shadow] focus-within:border-highlight focus-within:ring-4 focus-within:ring-highlight/20 dark:focus-within:ring-0 sm:flex-nowrap"
    >
      <Input
        ref={input}
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Ask a question about your documents"
        aria-label="Question"
        aria-keyshortcuts="/"
        className="h-10 flex-1 border-0 bg-transparent px-3 shadow-none focus-visible:ring-0 sm:h-11 md:text-base dark:bg-transparent"
      />
      <ToggleGroup
        type="single"
        spacing={0.5}
        value="ask"
        onValueChange={(v) => {
          // Research is its own page. A question typed (and not yet asked here) starts a new conversation with it;
          // otherwise the conversation last open comes back.
          const next = text.trim()
          if (v === 'research') navigate({ to: '/research', search: { q: next && next !== q ? next : undefined } })
        }}
        aria-label="Mode"
        className="h-10 rounded-lg bg-muted p-[3px] max-sm:order-last max-sm:w-full sm:h-11"
      >
        <ToggleGroupItem value="ask" className={modeItem}>
          <SparklesIcon /> Ask
        </ToggleGroupItem>
        <ToggleGroupItem value="research" className={modeItem}>
          <MessagesSquareIcon /> Research
        </ToggleGroupItem>
      </ToggleGroup>
      <Button
        type="submit"
        size="icon-lg"
        className="size-10 rounded-lg sm:size-11"
        aria-label="Ask"
        title="Ask"
      >
        <ArrowRightIcon />
      </Button>
    </form>
  )
}

const forever = { staleTime: Infinity, gcTime: Infinity }
const row = 'flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between'
// Messages from the server (app/backend/rag/search.py, answer.py) that trying again right away cannot change.
const final = /^(No matching pages|No documents yet|Type a question|Daily free limit)/

function Results({ q, quota }: { q: string; quota?: string | null }) {
  const queryClient = useQueryClient()
  const [viewer, setViewer] = useState<ViewerPage | null>(null)
  const refreshQuota = () => void queryClient.invalidateQueries({ queryKey: ['quota'] })
  // Asking is never retried automatically.
  const ask = useQuery({
    queryKey: ['ask', q],
    queryFn: async () => {
      const r = await api.ask(q).finally(refreshQuota)
      // A re-ask that only returns a message (rate limit, daily limit) keeps the answer already paid for.
      const prev = queryClient.getQueryData<AskResult>(['ask', q])
      return r.answer || !prev?.answer ? r : { ...prev, message: r.message }
    },
    ...forever,
  })
  const groups = ask.data?.groups ?? []
  const message = ask.data?.message
  const empty =
    message === 'No matching pages.'
      ? `No pages match “${q}”.`
      : message === 'No documents yet.' && 'No documents yet. Add PDFs, Word files or links first.'
  const matches = groups.length === 1 ? '1 document matches' : `${groups.length} documents match`
  const tryAgain = <TryAgain busy={ask.isFetching} onClick={() => ask.refetch({ cancelRefetch: false })} />

  return (
    <div className="space-y-6">
      <h1 className="sr-only">{q}</h1>
      <AskForm q={q} />
      <p role="status" className="sr-only">
        {ask.isFetching
          ? 'Reading the best pages…'
          : ask.data?.answer
            ? 'Answer ready'
            : groups.length
              ? matches
              : empty || ''}
      </p>
      {ask.isPending && <Loading />}
      {ask.error && (
        <Warning error>
          <span className={row}>
            Could not get an answer ({ask.error.message}).
            {tryAgain}
          </span>
        </Warning>
      )}
      {empty ? (
        <p className="py-12 text-center text-sm text-muted-foreground wrap-anywhere">{empty}</p>
      ) : (
        message && (
          <Warning>
            <span className={row}>
              <span className="block first-letter:uppercase">{message}</span>
              {!final.test(message) && tryAgain}
            </span>
          </Warning>
        )
      )}
      {ask.data?.answer && (
        <Card className={ask.isFetching ? 'opacity-60' : ''}>
          <CardContent className="space-y-4">
            <AnswerView answer={ask.data.answer} onOpen={setViewer} />
            <div className="flex items-center justify-between gap-4 border-t pt-3 text-xs text-muted-foreground">
              <span className="min-w-0">
                Answered by {ask.data.answer.model}
                {quota && ` · ${quota}`}
              </span>
              <Button
                variant="ghost"
                size="sm"
                aria-disabled={ask.isFetching}
                onClick={() => !ask.isFetching && ask.refetch({ cancelRefetch: false })}
              >
                {ask.isFetching ? <Spinner /> : <RotateCwIcon />} Ask again
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      {groups.length > 0 && (
        <section className={cn('space-y-3', ask.isFetching && !ask.isPending && 'opacity-60')}>
          <h2 className="text-sm font-medium text-muted-foreground">All matching pages</h2>
          <SearchResults groups={groups} onOpen={setViewer} />
        </section>
      )}
      <PageViewer page={viewer} onChange={setViewer} />
    </div>
  )
}

function Loading() {
  return (
    <Card>
      <CardContent className="space-y-3">
        <p className="flex items-start gap-2 text-sm text-muted-foreground [&>svg]:mt-0.5">
          <Spinner />
          Reading the best pages. This takes a few seconds.
        </p>
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-2/3" />
      </CardContent>
    </Card>
  )
}

function TryAgain({ busy, onClick }: { busy: boolean; onClick: () => void }) {
  return (
    <Button
      variant="outline"
      size="sm"
      className="shrink-0 sm:-my-1"
      aria-disabled={busy}
      onClick={() => !busy && onClick()}
    >
      {busy ? <Spinner /> : <RotateCwIcon />} Try again
    </Button>
  )
}
