import { useState, type KeyboardEvent } from 'react'
import { Link } from '@tanstack/react-router'
import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react'
import { pageUrl } from '@/api'
import { ExternalLink } from '@/components/external-link'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { displayTitle, fileLabel, useLibrary } from '@/lib/library'

// label: the citation ("S1") when opened from an answer; dropped once you page away from it.
export type ViewerPage = { docId: number; page: number; label?: string }

type Props = { page: ViewerPage | null; onChange: (page: ViewerPage | null) => void; docLink?: boolean }

// One page large, with ←/→ through its document. Title, page count and file links come from the library.
export function PageViewer({ page, onChange, docLink = true }: Props) {
  const doc = useLibrary().data?.docs.find((d) => d.id === page?.docId)
  if (!page) return null
  const count = doc?.page_count ?? null
  const go = (n: number) => count && n >= 1 && n <= count && onChange({ docId: page.docId, page: n })
  const keys = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') go(page.page - 1)
    if (e.key === 'ArrowRight') go(page.page + 1)
  }
  const link = '-my-2 inline-flex items-center gap-1 py-2 text-muted-foreground hover:text-foreground hover:underline'

  return (
    <Dialog open onOpenChange={(open) => !open && onChange(null)}>
      <DialogContent
        className="sm:max-w-[min(64rem,calc(100%-2rem))]"
        onKeyDown={keys}
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          ;(e.currentTarget as HTMLElement).focus()
        }}
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle className="flex min-w-0 pr-8 leading-normal pointer-coarse:pr-10">
            <span className="truncate">
              {page.label && `${page.label} · `}
              {doc ? displayTitle(doc) : `Document ${page.docId}`}
            </span>
            <span className="shrink-0 whitespace-pre"> · page {page.page}{count && ` of ${count}`}</span>
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-wrap items-center justify-between gap-2 sm:flex-nowrap sm:justify-center">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Previous page"
            aria-disabled={!count || page.page <= 1}
            onClick={() => go(page.page - 1)}
          >
            <ChevronLeftIcon />
          </Button>
          <PageImage src={pageUrl(page.docId, page.page)} alt={`Page ${page.page}`} />
          <Button
            variant="ghost"
            size="icon"
            aria-label="Next page"
            aria-disabled={!count || page.page >= count}
            onClick={() => go(page.page + 1)}
          >
            <ChevronRightIcon />
          </Button>
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-1">
          {docLink && (
            <Link to="/docs/$id" params={{ id: String(page.docId) }} search={{ page: page.page }} className={link}>
              Open document
            </Link>
          )}
          {doc?.file_url && (
            <ExternalLink href={doc.file_url} className={link}>
              {fileLabel(doc)}
            </ExternalLink>
          )}
          <ExternalLink href={pageUrl(page.docId, page.page)} className={link}>
            Full-size image
          </ExternalLink>
          {doc?.kind === 'url' && (
            <ExternalLink href={doc.source} className={link}>
              Open link
            </ExternalLink>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

// Not keyed by src: the previous page stays visible until the next one has loaded.
function PageImage({ src, alt }: { src: string; alt: string }) {
  const [missing, setMissing] = useState<string | null>(null)
  if (missing === src)
    return (
      <p className="flex h-[50vh] flex-1 items-center justify-center text-muted-foreground max-sm:order-first max-sm:basis-full sm:h-[75vh]">
        Page image missing
      </p>
    )
  return (
    <div className="flex min-w-0 items-center justify-center max-sm:order-first max-sm:basis-full sm:h-[75vh]">
      <img
        src={src}
        alt={alt}
        onError={() => setMissing(src)}
        className="max-h-[70vh] max-w-full rounded-md border bg-white object-contain sm:max-h-full"
      />
    </div>
  )
}
