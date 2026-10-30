import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { RotateCwIcon, SearchIcon, SparklesIcon } from 'lucide-react'
import { api } from '@/api'
import { AddPanel } from '@/components/add-panel'
import { AnswerView } from '@/components/answer-view'
import { PageViewer, type ViewerPage } from '@/components/page-viewer'
import { SearchResults } from '@/components/search-results'
import { Warning } from '@/components/warning'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { isProcessing, useLibrary } from '@/lib/library'
import { useTitle } from '@/lib/title'

type Mode = 'ask' | 'search'

// "/": ask (default) or search. The question is in the URL (?q=…&mode=search), so Back/Forward work;
// results stay cached for the session, so coming back from a document does not ask again.
export function AskPage() {
  const { q, mode = 'ask' } = useSearch({ from: '/' })
  const library = useLibrary()
  useTitle(q || 'Ask')
  if (q) return <Results key={`${mode}:${q}`} q={q} mode={mode} />
  if (library.isSuccess && !library.data.docs.length) return <FirstRun />
  const docs = library.data?.docs ?? []
  const pages = docs.reduce((n, d) => n + (d.page_count ?? 0), 0)
  const processing = docs.filter(isProcessing).length
  return (
    <div className="mx-auto max-w-2xl space-y-4 pt-[12vh]">
      <h1 className="text-center text-2xl font-semibold">Ask your documents</h1>
      <AskForm mode={mode} />
      {docs.length > 0 && (
        <p className="text-center text-sm text-muted-foreground">
          {docs.length} {docs.length === 1 ? 'document' : 'documents'} · {pages} pages · answers cite the 3 best
          pages
          {processing > 0 && ` · ${processing} still processing; they can be found once they are ready`}
        </p>
      )}
    </div>
  )
}

function FirstRun() {
  return (
    <div className="mx-auto max-w-xl space-y-6 pt-[8vh]">
      <div className="space-y-2 text-center">
        <h1 className="text-2xl font-semibold">Welcome to PixelRAG</h1>
        <p className="text-muted-foreground">
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
    // The same question again is an explicit request for a fresh answer.
    if (next === q && m === mode) queryClient.refetchQueries({ queryKey: [m, q] })
    else navigate({ search: { q: next, mode: m === 'search' ? 'search' : undefined } })
  }

  return (
    <form onSubmit={submit} className="flex gap-2">
      <Input
        ref={input}
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={m === 'ask' ? 'Ask a question about your documents' : 'Search your documents'}
        aria-label="Question"
        className="h-10 flex-1"
      />
      <ToggleGroup
        type="single"
        variant="outline"
        spacing={0}
        value={m}
        onValueChange={(v) => v && setM(v as Mode)}
        aria-label="Mode"
      >
        <ToggleGroupItem value="ask" className="h-10 px-3">
          Ask
        </ToggleGroupItem>
        <ToggleGroupItem value="search" className="h-10 px-3">
          Search
        </ToggleGroupItem>
      </ToggleGroup>
      <Button type="submit" className="h-10 px-4">
        {m === 'ask' ? <SparklesIcon /> : <SearchIcon />}
        {m === 'ask' ? 'Ask' : 'Search'}
      </Button>
    </form>
  )
}

const forever = { staleTime: Infinity, gcTime: Infinity }

function Results({ q, mode }: { q: string; mode: Mode }) {
  const [viewer, setViewer] = useState<ViewerPage | null>(null)
  // Only the query for the current mode runs. Asking is never retried automatically (PLAN.md §6.2).
  const ask = useQuery({ queryKey: ['ask', q], queryFn: () => api.ask(q), enabled: mode === 'ask', ...forever })
  const search = useQuery({ queryKey: ['search', q], queryFn: () => api.search(q), enabled: mode === 'search', ...forever })
  const query = mode === 'ask' ? ask : search
  const groups = query.data?.groups ?? []

  return (
    <div className="space-y-6">
      <AskForm q={q} mode={mode} />
      {query.isPending && <Loading mode={mode} />}
      {query.error && (
        <Alert variant="destructive">
          <AlertDescription className="flex items-center justify-between gap-4">
            Can't reach the PixelRAG server ({query.error.message}).
            <TryAgain onClick={() => query.refetch()} />
          </AlertDescription>
        </Alert>
      )}
      {query.data?.message && (
        <Warning>
          <span className="flex items-center justify-between gap-4">
            {query.data.message}
            <TryAgain onClick={() => query.refetch()} />
          </span>
        </Warning>
      )}
      {mode === 'ask' && ask.data?.answer && (
        <Card className={ask.isFetching ? 'opacity-60' : ''}>
          <CardContent className="space-y-4">
            <AnswerView answer={ask.data.answer} onOpen={setViewer} />
            <div className="flex items-center justify-between gap-4 border-t pt-3 text-xs text-muted-foreground">
              Answered by {ask.data.answer.model}
              <Button variant="ghost" size="sm" disabled={ask.isFetching} onClick={() => ask.refetch()}>
                {ask.isFetching ? <Spinner /> : <RotateCwIcon />} Ask again
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      {groups.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">
            {mode === 'ask' ? 'All matching pages' : `${groups.length} ${groups.length === 1 ? 'document' : 'documents'} match`}
          </h2>
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
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner />
          {mode === 'ask' ? 'Reading the 3 best pages… this takes a few seconds.' : 'Searching…'}
        </p>
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-2/3" />
      </CardContent>
    </Card>
  )
}

function TryAgain({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="outline" size="sm" className="shrink-0" onClick={onClick}>
      <RotateCwIcon /> Try again
    </Button>
  )
}
