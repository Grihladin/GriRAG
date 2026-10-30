import { Link, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { ArrowLeftIcon, ExternalLinkIcon, TriangleAlertIcon } from 'lucide-react'
import { pageUrl, type Doc } from '@/api'
import { DocActions } from '@/components/doc-actions'
import { DocStatus, KindIcon } from '@/components/doc-status'
import { PageViewer } from '@/components/page-viewer'
import { Warning } from '@/components/warning'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { displayTitle, kindLabel, useDocAction, useLibrary } from '@/lib/library'

// /docs/$id: one document with all its pages; ?page=N opens the page viewer.
export function DocPage() {
  const id = Number(useParams({ from: '/docs/$id' }).id)
  const { page } = useSearch({ from: '/docs/$id' })
  const navigate = useNavigate({ from: '/docs/$id' })
  const library = useLibrary()
  const action = useDocAction()
  const doc = library.data?.docs.find((d) => d.id === id)
  const back = (
    <Link to="/library" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeftIcon className="size-4" /> Library
    </Link>
  )

  if (library.isPending)
    return (
      <div className="space-y-4">
        {back}
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  if (!doc)
    return (
      <div className="space-y-4">
        {back}
        <p className="text-muted-foreground">This document is not in the library (maybe it was deleted).</p>
      </div>
    )

  const link = 'inline-flex items-center gap-1 hover:text-foreground hover:underline'
  const notice = action.data?.message ?? action.error?.message
  return (
    <div className="space-y-5">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <h1 className="flex min-w-0 items-center gap-2 text-xl font-semibold break-all">
          <KindIcon kind={doc.kind} />
          {displayTitle(doc)}
        </h1>
        <DocActions doc={doc} action={action} onDeleted={() => navigate({ to: '/library' })} />
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
        <DocStatus doc={doc} clamp={false} />
        <span>{kindLabel(doc.kind)}</span>
        {doc.page_count !== null && <span>{doc.page_count} pages</span>}
        {doc.file_url && (
          <a href={doc.file_url} target="_blank" className={link}>
            Original file <ExternalLinkIcon className="size-3.5" />
          </a>
        )}
        {doc.kind === 'url' && (
          <a href={doc.source} target="_blank" rel="noreferrer" className={link}>
            Website <ExternalLinkIcon className="size-3.5" />
          </a>
        )}
      </div>
      {doc.warning && (
        <p className="flex gap-1.5 text-sm text-muted-foreground">
          <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" /> {doc.warning}
        </p>
      )}
      {notice && <Warning>{notice}</Warning>}
      <Pages doc={doc} onOpen={(n) => navigate({ search: { page: n }, resetScroll: false })} />
      <PageViewer
        page={page ? { docId: id, page } : null}
        onChange={(p) => navigate({ search: p ? { page: p.page } : {}, replace: true, resetScroll: false })}
        docLink={false}
      />
    </div>
  )
}

function Pages({ doc, onOpen }: { doc: Doc; onOpen: (page: number) => void }) {
  if (doc.page_count === null)
    return (
      <p className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
        {doc.status === 'working' && <Spinner />}
        {doc.status === 'error' ? 'No pages.' : 'The pages appear here once the document is converted.'}
      </p>
    )
  const n = doc.page_count
  return (
    <div className="space-y-2">
      {doc.status === 'working' && (
        <p className="text-sm text-muted-foreground">
          {doc.pages_embedded} of {n} pages searchable so far.
        </p>
      )}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-4">
        {Array.from({ length: n }, (_, i) => i + 1).map((p) => (
          <button key={p} type="button" onClick={() => onOpen(p)} className="group space-y-1 text-left">
            <img
              src={pageUrl(doc.id, p)}
              alt={`Page ${p}`}
              loading="lazy"
              className={`w-full rounded-md border bg-white object-contain group-hover:ring-2 group-hover:ring-ring ${doc.kind === 'url' ? 'aspect-square' : 'aspect-[3/4]'}`}
            />
            <span className="text-xs text-muted-foreground">p. {p}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
