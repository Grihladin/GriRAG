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
import { displayTitle, type useDocAction } from '@/lib/library'

type Props = { doc: Doc; action: ReturnType<typeof useDocAction>; compact?: boolean; onDeleted?: () => void }

// Retry (failed or waiting) and Delete (with a confirm); nothing while the document is being processed.
export function DocActions({ doc: d, action, compact, onDeleted }: Props) {
  if (d.status === 'working') return null
  return (
    <div className="flex justify-end gap-1">
      {(d.status === 'error' || d.waiting) && (
        <Button
          variant="outline"
          size={compact ? 'sm' : 'default'}
          disabled={action.isPending}
          onClick={() => action.mutate({ id: d.id, kind: 'retry' })}
        >
          <RotateCwIcon /> {d.waiting ? 'Retry now' : 'Retry'}
        </Button>
      )}
      <AlertDialog>
        <AlertDialogTrigger asChild>
          {compact ? (
            <Button variant="ghost" size="icon-sm" disabled={action.isPending} aria-label="Delete" title="Delete">
              <Trash2Icon />
            </Button>
          ) : (
            <Button variant="outline" disabled={action.isPending}>
              <Trash2Icon /> Delete
            </Button>
          )}
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {displayTitle(d)}?</AlertDialogTitle>
            <AlertDialogDescription>
              The document, its page images and its search index are removed. This cannot be undone.
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
