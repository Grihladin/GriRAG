import { Link } from '@tanstack/react-router'
import { ExternalLinkIcon } from 'lucide-react'
import type { Hit } from '@/api'
import { KindIcon } from '@/components/doc-status'
import type { ViewerPage } from '@/components/page-viewer'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { displayTitle } from '@/lib/library'

// Matching pages grouped by document, best document first.
export function SearchResults({ groups, onOpen }: { groups: Hit[][]; onOpen: (p: ViewerPage) => void }) {
  return (
    <div className="space-y-3">
      {groups.map((g) => (
        <Card key={g[0].doc_id}>
          <CardContent className="space-y-3">
            <div className="flex items-baseline justify-between gap-4">
              <Link
                to="/docs/$id"
                params={{ id: String(g[0].doc_id) }}
                className="flex min-w-0 items-center gap-2 font-medium break-all hover:underline"
              >
                <KindIcon kind={g[0].kind} />
                {displayTitle(g[0])}
              </Link>
              {g[0].kind === 'url' && (
                <a
                  href={g[0].source}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex shrink-0 items-center gap-1 text-sm text-muted-foreground hover:underline"
                >
                  Website <ExternalLinkIcon className="size-3.5" />
                </a>
              )}
            </div>
            <div className="flex flex-wrap gap-3">
              {g.map((h) => (
                <PageThumb key={h.page_no} hit={h} caption={`p. ${h.page_no} · ${h.score.toFixed(2)}`} onOpen={onOpen} />
              ))}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

type ThumbProps = { hit: Hit; caption: string; label?: string; highlight?: boolean; onOpen: (p: ViewerPage) => void }

export function PageThumb({ hit: h, caption, label, highlight, onOpen }: ThumbProps) {
  return (
    <button
      type="button"
      onClick={() => onOpen({ docId: h.doc_id, page: h.page_no, label })}
      className="group w-44 space-y-1 text-left"
    >
      <img
        src={h.image_url}
        alt={`${h.title}, page ${h.page_no}`}
        loading="lazy"
        className={cn(
          'w-full rounded-md border bg-white object-contain transition-shadow group-hover:ring-2 group-hover:ring-ring',
          h.kind === 'url' ? 'aspect-square' : 'aspect-[3/4]',
          highlight && 'ring-2 ring-primary',
        )}
      />
      <span className="block truncate text-xs text-muted-foreground" title={caption}>
        {caption}
      </span>
    </button>
  )
}
