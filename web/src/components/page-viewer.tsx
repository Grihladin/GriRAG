import { useState, type KeyboardEvent } from 'react'
import { Link } from '@tanstack/react-router'
import { ChevronLeftIcon, ChevronRightIcon, ExternalLinkIcon } from 'lucide-react'
import { pageUrl } from '@/api'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { displayTitle, useLibrary } from '@/lib/library'

// label: the citation ("S1") when opened from an answer; dropped once you page away from it.
export type ViewerPage = { docId: number; page: number; label?: string }

type Props = { page: ViewerPage | null; onChange: (page: ViewerPage | null) => void; docLink?: boolean }

// One page large, with ←/→ through its document. Title, page count and file links come from the library.
export function PageViewer({ page, onChange, docLink = true }: Props) {
  const doc = useLibrary().data?.docs.find((d) => d.id === page?.docId)
  if (!page) return <Dialog open={false} />
  const count = doc?.page_count ?? null
  const go = (n: number) => count && n >= 1 && n <= count && onChange({ docId: page.docId, page: n })
  const keys = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') go(page.page - 1)
    if (e.key === 'ArrowRight') go(page.page + 1)
  }
  const link = 'inline-flex items-center gap-1 text-muted-foreground hover:text-foreground hover:underline'

  return (
    <Dialog open onOpenChange={(open) => !open && onChange(null)}>
      <DialogContent className="sm:max-w-5xl" onKeyDown={keys} aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle className="truncate pr-8 leading-normal">
            {page.label && `${page.label} · `}
            {doc ? displayTitle(doc) : `Document ${page.docId}`} · page {page.page}
            {count && ` of ${count}`}
          </DialogTitle>
        </DialogHeader>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" aria-label="Previous page" disabled={!count || page.page <= 1} onClick={() => go(page.page - 1)}>
            <ChevronLeftIcon />
          </Button>
          <PageImage key={pageUrl(page.docId, page.page)} src={pageUrl(page.docId, page.page)} />
          <Button variant="ghost" size="icon" aria-label="Next page" disabled={!count || page.page >= count} onClick={() => go(page.page + 1)}>
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
            <a href={doc.file_url} target="_blank" className={link}>
              Original file <ExternalLinkIcon className="size-3.5" />
            </a>
          )}
          <a href={pageUrl(page.docId, page.page)} target="_blank" className={link}>
            Full-size image <ExternalLinkIcon className="size-3.5" />
          </a>
          {doc?.kind === 'url' && (
            <a href={doc.source} target="_blank" rel="noreferrer" className={link}>
              Website <ExternalLinkIcon className="size-3.5" />
            </a>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function PageImage({ src }: { src: string }) {
  const [missing, setMissing] = useState(false)
  if (missing)
    return <p className="flex h-[75vh] flex-1 items-center justify-center text-muted-foreground">Page image missing</p>
  return (
    <div className="flex h-[75vh] min-w-0 flex-1 items-center justify-center">
      <img src={src} alt="" onError={() => setMissing(true)} className="max-h-full max-w-full rounded-md border bg-white object-contain" />
    </div>
  )
}
