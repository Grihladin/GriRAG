import { RotateCwIcon, Trash2Icon } from 'lucide-react'
import type { Doc } from '@/api'
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
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { displayTitle, type useDocAction } from '@/lib/library'

type Props = { doc: Doc; action: ReturnType<typeof useDocAction>; compact?: boolean; onDeleted?: () => void }

// Retry (failed or waiting) and Delete (with a confirm); nothing while the document is being processed.
export function DocActions({ doc: d, action, compact, onDeleted }: Props) {
  if (d.status === 'working') return null
  const busy = action.isPending && action.variables?.id === d.id
  return (
    <div className="flex justify-end gap-1">
      {(d.status === 'error' || d.waiting) && (
        <Button
          variant="outline"
          size={compact ? 'sm' : 'default'}
          disabled={busy}
          aria-label={`${d.waiting ? 'Retry now' : 'Retry'}: ${displayTitle(d)}`}
          onClick={() => action.mutate({ id: d.id, kind: 'retry' })}
        >
          {busy && action.variables?.kind === 'retry' ? <Spinner /> : <RotateCwIcon />}
          {d.waiting ? 'Retry now' : 'Retry'}
        </Button>
      )}
      <AlertDialog>
        <AlertDialogTrigger asChild>
          {compact ? (
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={busy}
              aria-label={`Delete ${displayTitle(d)}`}
              title="Delete"
            >
              <Trash2Icon />
            </Button>
          ) : (
            <Button variant="outline" disabled={busy}>
              <Trash2Icon /> Delete
            </Button>
          )}
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="wrap-anywhere">Delete {displayTitle(d)}?</AlertDialogTitle>
            <AlertDialogDescription>
              Its page images and search index will be deleted too. This can't be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() =>
                action.mutate({ id: d.id, kind: 'delete' }, { onSuccess: (r) => !r.message && onDeleted?.() })
              }
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
