import { Link } from '@tanstack/react-router'
import { LibraryIcon, PlusIcon, TriangleAlertIcon } from 'lucide-react'
import { DocActions } from '@/components/doc-actions'
import { DocStatus, KindIcon } from '@/components/doc-status'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useOpenAdd } from '@/lib/add-context'
import { displayTitle, plural, useDocAction, useLibrary } from '@/lib/library'
import { useTitle } from '@/lib/title'

export function LibraryPage() {
  const library = useLibrary()
  useTitle('Library')
  const action = useDocAction()
  const docs = library.data?.docs ?? []
  const pages = docs.reduce((n, d) => n + (d.page_count ?? 0), 0)
  const notice = action.data?.message ?? action.error?.message

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="text-xl font-semibold">Library</h1>
        {docs.length > 0 && (
          <span className="text-sm text-muted-foreground">
            {plural(docs.length, 'document')} · {plural(pages, 'page')}
          </span>
        )}
      </div>
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
      {library.data && !docs.length && <EmptyLibrary />}
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
