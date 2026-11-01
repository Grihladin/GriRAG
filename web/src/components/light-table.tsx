import { Link } from '@tanstack/react-router'
import { CircleXIcon, ClockIcon } from 'lucide-react'
import { pageUrl, type Doc } from '@/api'
import { Spinner } from '@/components/ui/spinner'
import { displayTitle, plural, statusLabel } from '@/lib/library'
import { cn } from '@/lib/utils'

const SHOWN = 24

// The library on the home page: the first page of each document, newest first. Documents with more than one page
// sit on a stack.
export function LightTable({ docs, processing }: { docs: Doc[]; processing: number }) {
  const pages = docs.reduce((n, d) => n + (d.page_count ?? 0), 0)
  return (
    <section aria-labelledby="light-table" className="space-y-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b pb-2">
        <h2 id="light-table" className="font-heading text-lg font-semibold tracking-[-0.01em]">
          Your library
        </h2>
        <p className="text-sm text-muted-foreground">
          {plural(docs.length, 'document')}, {plural(pages, 'page')}
          {processing > 0 && `, ${processing} processing`}
          <Link to="/library" className="ml-4 font-medium underline decoration-highlight decoration-2 underline-offset-4 hover:decoration-foreground">
            {docs.length > SHOWN ? `See all ${docs.length}` : 'Open library'}
          </Link>
        </p>
      </div>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(6.5rem,1fr))] gap-x-5 gap-y-6">
        {docs.slice(0, SHOWN).map((d) => (
          <li key={d.id}>
            <Link
              to="/docs/$id"
              params={{ id: String(d.id) }}
              title={displayTitle(d)}
              className="group block space-y-2 rounded-sm outline-none"
            >
              {d.page_count ? (
                <div
                  className={cn(
                    'aspect-[3/4] rounded-[3px] bg-white ring-1 ring-foreground/10 transition-shadow group-hover:ring-3 group-hover:ring-highlight group-hover:ring-offset-2 group-hover:ring-offset-background group-focus-visible:ring-2 group-focus-visible:ring-ring dark:brightness-90 dark:group-hover:brightness-100',
                    d.page_count > 1 && 'shadow-[4px_4px_0_-1px_var(--card),4px_4px_0_0_var(--border)]',
                  )}
                >
                  <img
                    src={pageUrl(d.id, 1)}
                    alt=""
                    loading="lazy"
                    className="size-full rounded-[3px] object-cover object-top"
                  />
                </div>
              ) : (
                <Pending doc={d} />
              )}
              <span className="block space-y-0.5 text-xs leading-snug">
                <span className="line-clamp-2 font-medium wrap-anywhere group-hover:underline">{displayTitle(d)}</span>
                <span className="block text-muted-foreground">
                  {d.page_count ? plural(d.page_count, 'page') : statusLabel(d.status)}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

// A document without page images yet: converting, queued, or failed.
function Pending({ doc: d }: { doc: Doc }) {
  const failed = d.status === 'error'
  return (
    <div
      className={cn(
        'flex aspect-[3/4] items-center justify-center rounded-[3px] border border-dashed text-muted-foreground group-focus-visible:ring-2 group-focus-visible:ring-ring',
        failed && 'text-destructive',
      )}
    >
      {failed ? <CircleXIcon className="size-5" /> : d.waiting ? <ClockIcon className="size-5" /> : <Spinner />}
    </div>
  )
}
