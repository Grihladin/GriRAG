import { useRef } from 'react'
import { Link, useNavigate, useParams, useRouter, useSearch } from '@tanstack/react-router'
import { ArrowLeftIcon, ExternalLinkIcon, FileQuestionIcon, TriangleAlertIcon } from 'lucide-react'
import { pageUrl, type Doc } from '@/api'
import { DocActions } from '@/components/doc-actions'
import { DocStatus, KindIcon } from '@/components/doc-status'
import { PageViewer } from '@/components/page-viewer'
import { Warning } from '@/components/warning'
import { Skeleton } from '@/components/ui/skeleton'
import { displayTitle, fileLabel, isCapture, kindLabel, plural, useDocAction, useLibrary } from '@/lib/library'
import { useTitle } from '@/lib/title'
import { cn } from '@/lib/utils'

// /docs/$id: one document with all its pages; ?page=N opens the page viewer.
export function DocPage() {
  const id = Number(useParams({ from: '/docs/$id' }).id)
  const { page } = useSearch({ from: '/docs/$id' })
  const navigate = useNavigate({ from: '/docs/$id' })
  const router = useRouter()
  // Opening pushes ?page=N; closing goes back to it instead of leaving a duplicate history entry.
  const pushed = useRef(false)
  const library = useLibrary()
  const action = useDocAction()
  const doc = library.data?.docs.find((d) => d.id === id)
  useTitle(doc ? displayTitle(doc) : 'Document')
  // The flex wrapper keeps the parent's space-y margin, which -my-2 on the link itself would override.
  const back = (
    <div className="flex">
      <Link
        to="/library"
        className="-my-2 inline-flex items-center gap-1 py-2 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeftIcon className="size-4" /> Library
      </Link>
    </div>
  )

  if (!library.data) {
    if (library.isError)
      return (
        <div className="space-y-6">
          {back}
          <p className="py-16 text-center text-sm text-balance text-muted-foreground">
            This document can't be shown while the server is unreachable.
          </p>
        </div>
      )
    return (
      <div className="space-y-4">
        {back}
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (!doc)
    return (
      <div className="space-y-6">
        {back}
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16 text-center">
          <FileQuestionIcon className="size-8 text-muted-foreground" />
          <h1 className="font-medium">Document not found</h1>
          <p className="text-sm text-muted-foreground">It may have been deleted.</p>
        </div>
      </div>
    )

  const link = '-my-2 inline-flex items-center gap-1 py-2 hover:text-foreground hover:underline'
  const notice = action.data?.message ?? action.error?.message
  return (
    <div className="space-y-6">
      <div className="space-y-3">
        {back}
        <div className="space-y-2">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <h1 className="flex min-h-8 min-w-0 items-start gap-2 text-xl font-semibold wrap-anywhere [&>svg]:mt-1.5">
              <KindIcon kind={doc.kind} />
              {displayTitle(doc)}
            </h1>
            <DocActions doc={doc} action={action} onDeleted={() => navigate({ to: '/library', replace: true })} />
          </div>
          <div className="flex flex-wrap items-start gap-x-5 gap-y-2 text-sm text-muted-foreground">
            <DocStatus doc={doc} message={false} />
            <span>{kindLabel(doc)}</span>
            {doc.page_count !== null && <span>{plural(doc.page_count, 'page')}</span>}
            {doc.file_url && (
              <a href={doc.file_url} target="_blank" className={link}>
                {fileLabel(doc)} <ExternalLinkIcon className="size-3.5" />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            )}
            {doc.kind === 'url' && (
              <a href={doc.source} target="_blank" rel="noreferrer" className={link}>
                Open link <ExternalLinkIcon className="size-3.5" />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            )}
          </div>
        </div>
      </div>
      {doc.message && (
        <Warning error={doc.status === 'error'}>
          <span className="block first-letter:uppercase">{doc.message}</span>
        </Warning>
      )}
      {doc.warning && (
        <p className="flex gap-1.5 text-sm text-muted-foreground">
          <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" />
          <span className="first-letter:uppercase">{doc.warning}</span>
        </p>
      )}
      {notice && (
        <Warning>
          <span className="block first-letter:uppercase">{notice}</span>
        </Warning>
      )}
      <Pages
        doc={doc}
        onOpen={(n) => {
          pushed.current = true
          navigate({ search: { page: n }, resetScroll: false })
        }}
      />
      <PageViewer
        page={page && doc.page_count && page <= doc.page_count ? { docId: id, page } : null}
        onChange={(p) => {
          if (p) navigate({ search: { page: p.page }, replace: true, resetScroll: false })
          else if (pushed.current) {
            pushed.current = false
            router.history.back()
          } else navigate({ search: {}, replace: true, resetScroll: false })
        }}
        docLink={false}
      />
    </div>
  )
}

function Pages({ doc, onOpen }: { doc: Doc; onOpen: (page: number) => void }) {
  if (doc.page_count === null)
    return (
      <p className="py-8 text-sm text-muted-foreground">
        {doc.status === 'error' ? 'No pages yet.' : 'The pages appear here once the document is converted.'}
      </p>
    )
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-4">
      {Array.from({ length: doc.page_count }, (_, i) => i + 1).map((p) => (
        <button
          key={p}
          type="button"
          aria-label={`Page ${p}`}
          onClick={() => onOpen(p)}
          className="group space-y-1 text-left outline-none"
        >
          <img
            src={pageUrl(doc.id, p)}
            alt=""
            loading="lazy"
            className={cn(
              'w-full rounded-md border bg-white object-contain transition-[box-shadow,filter] group-hover:ring-3 group-hover:ring-highlight group-hover:ring-offset-2 group-hover:ring-offset-background group-focus-visible:ring-2 group-focus-visible:ring-ring dark:brightness-85 dark:group-hover:brightness-100',
              isCapture(doc) ? 'aspect-square' : 'aspect-[3/4]',
            )}
          />
          <span className="block text-xs text-muted-foreground">p. {p}</span>
        </button>
      ))}
    </div>
  )
}
