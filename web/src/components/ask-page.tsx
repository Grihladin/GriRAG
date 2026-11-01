import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { ArrowRightIcon, RotateCwIcon, SearchIcon, SparklesIcon } from 'lucide-react'
import { api, type AskResult } from '@/api'
import { AddPanel } from '@/components/add-panel'
import { AnswerView } from '@/components/answer-view'
import { PageViewer, type ViewerPage } from '@/components/page-viewer'
import { SearchResults } from '@/components/search-results'
import { Warning } from '@/components/warning'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { isProcessing, plural, useLibrary } from '@/lib/library'
import { useTitle } from '@/lib/title'
import { cn } from '@/lib/utils'

type Mode = 'ask' | 'search'

// "/": ask (default) or search. The question is in the URL (?q=…&mode=search), so Back/Forward work;
// results stay cached for the session, so coming back from a document does not ask again.
export function AskPage() {
  const { q, mode = 'ask' } = useSearch({ from: '/' })
  const library = useLibrary()
  const quota = useQuery({ queryKey: ['quota'], queryFn: api.quota })
  useTitle(q || 'Ask')
  if (q) return <Results key={`${mode}:${q}`} q={q} mode={mode} quota={quota.data?.quota} />
  if (library.isSuccess && !library.data.docs.length) return <FirstRun />
  const docs = library.data?.docs ?? []
  const pages = docs.reduce((n, d) => n + (d.page_count ?? 0), 0)
  const processing = docs.filter(isProcessing).length
  return (
    <div className="mx-auto max-w-2xl space-y-4 pt-[12vh]">
      <h1 className="text-center text-2xl font-semibold">Ask your documents</h1>
      <AskForm mode={mode} />
      {docs.length > 0 && (
        <p className="text-center text-sm text-balance text-muted-foreground">
          {plural(docs.length, 'document')} · {plural(pages, 'page')}
          {processing > 0 && ` · ${processing} still processing`}
        </p>
      )}
      {quota.data?.quota && <p className="text-center text-xs text-muted-foreground">{quota.data.quota}</p>}
    </div>
  )
}

function FirstRun() {
  return (
    <div className="mx-auto max-w-xl space-y-6 pt-[8vh]">
      <div className="space-y-2 text-center">
        <h1 className="text-2xl font-semibold">Welcome to PixelRAG</h1>
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
  'h-full rounded-md px-2.5 text-muted-foreground hover:text-foreground data-[state=on]:bg-background data-[state=on]:text-foreground data-[state=on]:shadow-sm max-sm:flex-1'

function AskForm({ q = '', mode }: { q?: string; mode: Mode }) {
  const navigate = useNavigate({ from: '/' })
  const queryClient = useQueryClient()
  const [text, setText] = useState(q)
  const [m, setM] = useState(mode)
  const input = useRef<HTMLInputElement>(null)

  // "/" focuses the box from anywhere on the page, as on most search sites.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && e.target.closest('input, textarea, [contenteditable]')
      if (e.key === '/' && !typing) {
        e.preventDefault()
        input.current?.focus()
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [])

  function submit(e: FormEvent) {
    e.preventDefault()
    const next = text.trim()
    if (!next) return
    // Submitting a question (again) is an explicit request for a fresh answer; Back/Forward reuse the cache.
    if (next === q && m === mode) {
      queryClient.refetchQueries({ queryKey: [m, q] }, { cancelRefetch: false })
    } else {
      queryClient.removeQueries({ queryKey: [m, next], exact: true })
      navigate({ search: { q: next, mode: m === 'search' ? 'search' : undefined } })
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap gap-2 sm:flex-nowrap">
      <Input
        ref={input}
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={m === 'ask' ? 'Ask a question about your documents' : 'Search your documents'}
        aria-label="Question"
        aria-keyshortcuts="/"
        className="h-10 flex-1"
      />
      <ToggleGroup
        type="single"
        spacing={0.5}
        value={m}
        onValueChange={(v) => {
          if (!v) return
          setM(v as Mode)
          // On a results page the toggle switches what is shown, like tabs.
          if (q && text.trim() === q) navigate({ search: { q, mode: v === 'search' ? 'search' : undefined } })
        }}
        aria-label="Mode"
        className="h-10 rounded-lg bg-muted p-[3px] max-sm:order-last max-sm:w-full"
      >
        <ToggleGroupItem value="ask" className={modeItem}>
          <SparklesIcon /> Ask
        </ToggleGroupItem>
        <ToggleGroupItem value="search" className={modeItem}>
          <SearchIcon /> Search
        </ToggleGroupItem>
      </ToggleGroup>
      <Button
        type="submit"
        size="icon-lg"
        className="size-10"
        aria-label={m === 'ask' ? 'Ask' : 'Search'}
        title={m === 'ask' ? 'Ask' : 'Search'}
      >
        <ArrowRightIcon />
      </Button>
    </form>
  )
}

const forever = { staleTime: Infinity, gcTime: Infinity }
const row = 'flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between'
// Messages from app/main.py that trying again right away cannot change.
const final = /^(No matching pages|No documents yet|Type a question|Daily free limit)/

function Results({ q, mode, quota }: { q: string; mode: Mode; quota?: string | null }) {
  const queryClient = useQueryClient()
  const [viewer, setViewer] = useState<ViewerPage | null>(null)
  const refreshQuota = () => void queryClient.invalidateQueries({ queryKey: ['quota'] })
  // Only the query for the current mode runs. Asking is never retried automatically (PLAN.md §6.2).
  const ask = useQuery({
    queryKey: ['ask', q],
    queryFn: async () => {
      const r = await api.ask(q).finally(refreshQuota)
      // A re-ask that only returns a message (rate limit, daily limit) keeps the answer already paid for.
      const prev = queryClient.getQueryData<AskResult>(['ask', q])
      return r.answer || !prev?.answer ? r : { ...prev, message: r.message }
    },
    enabled: mode === 'ask',
    ...forever,
  })
  const search = useQuery({
    queryKey: ['search', q],
    queryFn: () => api.search(q).finally(refreshQuota),
    enabled: mode === 'search',
    ...forever,
  })
  const query = mode === 'ask' ? ask : search
  const groups = query.data?.groups ?? []
  const message = query.data?.message
  const empty =
    message === 'No matching pages.'
      ? `No pages match “${q}”.`
      : message === 'No documents yet.' && 'No documents yet. Add PDFs, Word files or links first.'
  const matches = groups.length === 1 ? '1 document matches' : `${groups.length} documents match`
  const tryAgain = <TryAgain busy={query.isFetching} onClick={() => query.refetch({ cancelRefetch: false })} />

  return (
    <div className="space-y-6">
      <h1 className="sr-only">{q}</h1>
      <AskForm q={q} mode={mode} />
      <p role="status" className="sr-only">
        {query.isFetching
          ? mode === 'ask'
            ? 'Reading the 3 best pages…'
            : 'Searching…'
          : mode === 'ask' && ask.data?.answer
            ? 'Answer ready'
            : groups.length
              ? matches
              : empty || ''}
      </p>
      {query.isPending && <Loading mode={mode} />}
      {query.error && (
        <Warning error>
          <span className={row}>
            {mode === 'ask' ? 'Could not get an answer' : 'Search failed'} ({query.error.message}).
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
      {mode === 'ask' && ask.data?.answer && (
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
        <section className={cn('space-y-3', query.isFetching && !query.isPending && 'opacity-60')}>
          <h2 className="text-sm font-medium text-muted-foreground">{mode === 'ask' ? 'All matching pages' : matches}</h2>
          <SearchResults groups={groups} onOpen={setViewer} />
        </section>
      )}
      <PageViewer page={viewer} onChange={setViewer} />
    </div>
  )
}

function Loading({ mode }: { mode: Mode }) {
  return (
    <Card>
      <CardContent className="space-y-3">
        <p className="flex items-start gap-2 text-sm text-muted-foreground [&>svg]:mt-0.5">
          <Spinner />
          {mode === 'ask' ? 'Reading the 3 best pages. This takes a few seconds.' : 'Searching…'}
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
