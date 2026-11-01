import { useEffect, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { LibraryIcon, PlusIcon, SearchIcon, TriangleAlertIcon, XIcon } from 'lucide-react'
import { DocActions } from '@/components/doc-actions'
import { DocStatus, KindIcon } from '@/components/doc-status'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { Doc } from '@/api'
import { useOpenAdd } from '@/lib/add-context'
import { displayTitle, plural, useDocAction, useLibrary } from '@/lib/library'
import { useTitle } from '@/lib/title'

export function LibraryPage() {
  const library = useLibrary()
  useTitle('Library')
  const action = useDocAction()
  const all = library.data?.docs ?? []
  const [filter, setFilter] = useState('')
  const docs = all.filter(matches(filter))
  const pages = all.reduce((n, d) => n + (d.page_count ?? 0), 0)
  const notice = action.data?.message ?? action.error?.message

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <div className="flex items-baseline gap-4">
          <h1 className="font-heading text-[1.75rem] leading-tight font-bold tracking-[-0.025em]">Library</h1>
          {all.length > 0 && (
            <span className="text-sm text-muted-foreground">
              {docs.length < all.length
                ? `${docs.length} of ${plural(all.length, 'document')}`
                : `${plural(all.length, 'document')}, ${plural(pages, 'page')}`}
            </span>
          )}
        </div>
        {all.length > 0 && <Filter value={filter} onChange={setFilter} />}
      </div>
      {all.length > 0 && !docs.length && (
        <p className="py-12 text-center text-sm text-muted-foreground wrap-anywhere">
          No document titles or links contain “{filter.trim()}”.{' '}
          <button type="button" className="font-medium underline decoration-highlight decoration-2 underline-offset-4 hover:decoration-foreground" onClick={() => setFilter('')}>
            Show all
          </button>
        </p>
      )}
      {!library.data && !library.isError && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      )}
      {!library.data && library.isError && (
        <p className="py-16 text-center text-sm text-balance text-muted-foreground">
          The library can't be shown while the server is unreachable.
        </p>
      )}
      {library.data && !all.length && <EmptyLibrary />}
      {docs.length > 0 && (
        <div className="-mx-2">
          <Table>
            <TableHeader className="max-md:hidden">
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead className="hidden w-16 md:table-cell">Pages</TableHead>
                <TableHead className="hidden w-60 md:table-cell lg:w-72">Status</TableHead>
                <TableHead className="w-40" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {docs.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="max-w-md align-top whitespace-normal">
                    <Link
                      to="/docs/$id"
                      params={{ id: String(d.id) }}
                      className="flex items-start gap-2 font-medium wrap-anywhere hover:underline [&>svg]:mt-0.5"
                    >
                      <KindIcon kind={d.kind} />
                      {displayTitle(d)}
                    </Link>
                    {d.warning && (
                      <p className="mt-1 flex gap-1.5 pl-6 text-xs text-muted-foreground">
                        <TriangleAlertIcon className="mt-px size-3.5 shrink-0" />
                        <span className="first-letter:uppercase">{d.warning}</span>
                      </p>
                    )}
                    <div className="mt-1.5 pl-6 md:hidden">
                      <DocStatus doc={d} />
                    </div>
                    {notice && action.variables?.id === d.id && (
                      <p className="mt-1 pl-6 text-xs text-amber-700 first-letter:uppercase dark:text-amber-400">
                        {notice}
                      </p>
                    )}
                  </TableCell>
                  <TableCell className="hidden align-top text-muted-foreground md:table-cell">
                    {d.page_count ?? '—'}
                  </TableCell>
                  <TableCell className="hidden align-top whitespace-normal md:table-cell">
                    <DocStatus doc={d} />
                  </TableCell>
                  <TableCell className="py-1 align-top">
                    <DocActions doc={d} action={action} compact />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

// Every word must appear in the title or the link, in any case: "wiki pdf" finds en.wikipedia.org/wiki/PDF.
const matches = (filter: string) => {
  const words = filter.toLowerCase().split(/\s+/).filter(Boolean)
  return (d: Doc) => {
    const text = `${displayTitle(d)} ${d.source}`.toLowerCase()
    return words.every((w) => text.includes(w))
  }
}

// Narrows the table as you type; "/" focuses it, Escape clears it.
function Filter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const input = useRef<HTMLInputElement>(null)
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
  return (
    <div className="relative w-full sm:w-72">
      <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        ref={input}
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && value && (e.preventDefault(), onChange(''))}
        placeholder="Filter by title or link"
        aria-label="Filter documents by title or link"
        aria-keyshortcuts="/"
        className="h-9 bg-card pr-8 pl-8 [&::-webkit-search-cancel-button]:hidden"
      />
      {value && (
        <button
          type="button"
          aria-label="Clear filter"
          onClick={() => {
            onChange('')
            input.current?.focus()
          }}
          className="absolute top-1/2 right-1 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <XIcon className="size-4" />
        </button>
      )}
    </div>
  )
}

function EmptyLibrary() {
  const openAdd = useOpenAdd()
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16 text-center">
      <LibraryIcon className="size-8 text-muted-foreground" />
      <p className="font-medium">No documents yet</p>
      <p className="max-w-sm text-sm text-muted-foreground">
        Add PDFs, Word files or web links. Every page becomes an image you can search and ask about.
      </p>
      <Button onClick={() => openAdd()}>
        <PlusIcon /> Add documents
      </Button>
    </div>
  )
}
