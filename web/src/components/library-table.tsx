import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Doc } from '@/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export function LibraryTable() {
  const queryClient = useQueryClient()
  // The server says how often to poll: 2 s while something can be worked on, 30 s while only waiting, else stop.
  const library = useQuery({
    queryKey: ['library'],
    queryFn: api.library,
    refetchInterval: (query) => query.state.data?.poll_ms ?? false,
  })
  const action = useMutation({
    mutationFn: ({ id, kind }: { id: number; kind: 'retry' | 'delete' }) =>
      kind === 'retry' ? api.retry(id) : api.remove(id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['library'] }),
  })

  const notice = action.data?.message ? `#${action.variables?.id}: ${action.data.message}` : action.error?.message
  const banner = library.data?.banner
  const docs = library.data?.docs ?? []
  return (
    <Card>
      <CardHeader>
        <CardTitle>Library</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {library.error && (
          <Alert variant="destructive">
            <AlertDescription>Could not load the library: {library.error.message}</AlertDescription>
          </Alert>
        )}
        {[banner, notice].filter(Boolean).map((text) => (
          <Alert key={text} className="border-amber-300 bg-amber-50 text-amber-900">
            <AlertDescription className="text-amber-900">{text}</AlertDescription>
          </Alert>
        ))}
        {library.isSuccess && !docs.length && <p className="text-sm text-muted-foreground">No documents yet.</p>}
        {docs.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead>Title</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Pages</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {docs.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="align-top">{d.id}</TableCell>
                  <TableCell className="max-w-md align-top whitespace-normal">
                    {d.kind === 'url' ? (
                      <a href={d.source} target="_blank" rel="noreferrer" className="break-all hover:underline">
                        {d.title}
                      </a>
                    ) : (
                      <span className="break-all">{d.title}</span>
                    )}
                    {d.warning && <p className="text-xs text-muted-foreground">⚠ {d.warning}</p>}
                  </TableCell>
                  <TableCell className="align-top">{d.kind}</TableCell>
                  <TableCell className="align-top">{d.page_count ? `${d.pages_embedded}/${d.page_count}` : ''}</TableCell>
                  <TableCell className="max-w-sm align-top whitespace-normal">
                    <Status doc={d} />
                  </TableCell>
                  <TableCell className="text-right align-top">
                    {d.status !== 'working' && (
                      <>
                        {(d.status === 'error' || d.waiting) && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={action.isPending}
                            onClick={() => action.mutate({ id: d.id, kind: 'retry' })}
                          >
                            Retry
                          </Button>
                        )}
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button variant="ghost" size="sm" disabled={action.isPending}>
                              Delete
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Delete #{d.id}?</AlertDialogTitle>
                              <AlertDialogDescription>
                                {d.title} is removed with its vectors and page images.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Cancel</AlertDialogCancel>
                              <AlertDialogAction
                                variant="destructive"
                                onClick={() => action.mutate({ id: d.id, kind: 'delete' })}
                              >
                                Delete
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function Status({ doc: d }: { doc: Doc }) {
  if (d.status === 'working') {
    if (d.page_count === null) return <Badge variant="outline">converting</Badge>
    return (
      <div className="space-y-1.5">
        <Badge variant="outline">
          embedding {d.pages_embedded}/{d.page_count}
        </Badge>
        <Progress value={(100 * d.pages_embedded) / d.page_count} className="w-32" />
      </div>
    )
  }
  const label = d.waiting ? 'waiting' : d.status
  const variant = d.status === 'error' ? 'destructive' : d.status === 'done' ? 'secondary' : 'outline'
  return (
    <div className="space-y-1">
      <Badge variant={variant}>{label}</Badge>
      {d.message && (
        <p className={d.status === 'error' ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'}>
          {d.message}
        </p>
      )}
    </div>
  )
}
