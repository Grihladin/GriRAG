import { useState, type DragEvent, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { FileTextIcon, UploadIcon, XIcon } from 'lucide-react'
import { api, type AddResult } from '@/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { statusLabel } from '@/lib/library'

type Props = { initialFiles?: File[]; onClose?: () => void }

// Files and links to add. Used in the Add dialog (with onClose) and as the home page of an empty library.
export function AddPanel({ initialFiles = [], onClose }: Props) {
  const queryClient = useQueryClient()
  const [files, setFiles] = useState(initialFiles)
  const [urls, setUrls] = useState('')
  const add = useMutation({
    mutationFn: api.add,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['library'] })
      setFiles([])
      setUrls('')
      if (!result.duplicates.length && !result.rejected.length) onClose?.()
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    form.append('urls', urls)
    add.mutate(form)
  }

  // Drops here stay here; drops elsewhere in the app open the Add dialog (AppShell).
  function drop(e: DragEvent) {
    e.preventDefault()
    e.stopPropagation()
    setFiles((f) => [...f, ...e.dataTransfer.files])
  }

  if (add.data && (add.data.duplicates.length || add.data.rejected.length))
    return <AddReport result={add.data} onMore={add.reset} onClose={onClose} />

  const empty = !files.length && !urls.trim()
  return (
    <form onSubmit={submit} onDragOver={(e) => e.preventDefault()} onDrop={drop} className="space-y-4">
      <label className="flex cursor-pointer flex-col items-center gap-1 rounded-lg border-2 border-dashed p-8 text-center hover:bg-muted/50">
        <UploadIcon className="mb-1 size-6 text-muted-foreground" />
        <span className="font-medium">Drop PDF or Word files here</span>
        <span className="text-xs text-muted-foreground">or click to choose (.pdf, .docx)</span>
        <input
          type="file"
          multiple
          accept=".pdf,.docx"
          className="sr-only"
          onChange={(e) => {
            setFiles((f) => [...f, ...(e.target.files ?? [])])
            e.target.value = ''
          }}
        />
      </label>
      {files.length > 0 && (
        <ul className="space-y-1 text-sm">
          {files.map((f, i) => (
            <li key={i} className="flex items-center gap-2">
              <FileTextIcon className="size-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{f.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{(f.size / 1e6).toFixed(1)} MB</span>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={`Remove ${f.name}`}
                onClick={() => setFiles((all) => all.filter((_, j) => j !== i))}
              >
                <XIcon />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="space-y-1.5">
        <label htmlFor="add-urls" className="text-sm font-medium">
          Links
        </label>
        <Textarea
          id="add-urls"
          rows={3}
          placeholder="https://… (one per line)"
          value={urls}
          onChange={(e) => setUrls(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          Web pages are captured as images, up to 40 pages each. Links to PDF or Word files are downloaded.
        </p>
      </div>
      {add.error && (
        <Alert variant="destructive">
          <AlertDescription>Could not add: {add.error.message}</AlertDescription>
        </Alert>
      )}
      <div className="flex justify-end gap-2">
        {onClose && (
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={empty || add.isPending}>
          {add.isPending ? 'Adding…' : 'Add'}
        </Button>
      </div>
    </form>
  )
}

// Shown when something was a duplicate or rejected; plain successes just close the dialog.
function AddReport({ result, onMore, onClose }: { result: AddResult; onMore: () => void; onClose?: () => void }) {
  const { added, duplicates, rejected } = result
  return (
    <div className="space-y-4 text-sm">
      {added > 0 && (
        <p>
          Added {added} {added === 1 ? 'document' : 'documents'}. They are processed in the background; follow them
          in the{' '}
          <Link to="/library" className="underline" onClick={onClose}>
            library
          </Link>
          .
        </p>
      )}
      {duplicates.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium">Already in your library</p>
          <ul className="space-y-1">
            {duplicates.map((d) => (
              <li key={d.id}>
                {d.title} ({statusLabel(d.status)}) ·{' '}
                <Link to="/docs/$id" params={{ id: String(d.id) }} className="underline" onClick={onClose}>
                  Open
                </Link>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">To add one again (e.g. to refresh a web page), delete it first.</p>
        </div>
      )}
      {rejected.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium">Not added</p>
          <ul className="space-y-1 text-destructive">
            {rejected.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onMore}>
          Add more
        </Button>
        {onClose && <Button onClick={onClose}>Done</Button>}
      </div>
    </div>
  )
}
