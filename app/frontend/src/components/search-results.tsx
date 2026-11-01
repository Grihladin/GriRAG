import { Link } from '@tanstack/react-router'
import type { Hit } from '@/api'
import { KindIcon } from '@/components/doc-status'
import { ExternalLink } from '@/components/external-link'
import type { ViewerPage } from '@/components/page-viewer'
import { Card, CardContent } from '@/components/ui/card'
import { displayTitle } from '@/lib/library'
import { cn } from '@/lib/utils'

// Matching pages grouped by document, best document first.
export function SearchResults({ groups, onOpen }: { groups: Hit[][]; onOpen: (p: ViewerPage) => void }) {
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      {groups.map((g) => (
        <Card key={g[0].doc_id}>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between gap-4">
              <Link
                to="/docs/$id"
                params={{ id: String(g[0].doc_id) }}
                className="flex min-w-0 items-start gap-2 font-medium wrap-anywhere hover:underline [&>svg]:mt-0.5"
              >
                <KindIcon kind={g[0].kind} />
                {displayTitle(g[0])}
              </Link>
              {g[0].kind === 'url' && (
                <ExternalLink
                  href={g[0].source}
                  className="-my-2 inline-flex shrink-0 items-center gap-1 py-2 text-sm text-muted-foreground hover:text-foreground hover:underline"
                >
                  Open link
                </ExternalLink>
              )}
            </div>
            <div className="grid grid-cols-2 items-start gap-3 sm:flex sm:flex-wrap">
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
      aria-label={`${label ? `${label}: ` : ''}${displayTitle(h)}, page ${h.page_no}`}
      onClick={() => onOpen({ docId: h.doc_id, page: h.page_no, label })}
      className="group space-y-1 text-left outline-none sm:w-40"
    >
      <img
        src={h.image_url}
        alt=""
        loading="lazy"
        className={cn(
          'aspect-[3/4] w-full rounded-md border bg-white object-contain object-top transition-[box-shadow,filter] group-hover:ring-3 group-hover:ring-highlight group-hover:ring-offset-2 group-hover:ring-offset-card group-focus-visible:ring-2 group-focus-visible:ring-ring dark:brightness-85 dark:group-hover:brightness-100',
          highlight && 'ring-3 ring-highlight ring-offset-2 ring-offset-card',
        )}
      />
      <span className="block truncate text-xs text-muted-foreground" title={caption}>
        {caption}
      </span>
    </button>
  )
}
