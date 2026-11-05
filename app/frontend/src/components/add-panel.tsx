import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { FileTextIcon, UploadIcon, XIcon } from 'lucide-react'
import { api, type AddResult } from '@/api'
import { Warning } from '@/components/warning'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { plural, statusLabel, stripScheme } from '@/lib/library'

type Props = { initialFiles?: File[]; onClose?: () => void }

// Files and links to add. Used in the Add dialog (with onClose) and as the home page of an empty library.
export function AddPanel({ initialFiles = [], onClose }: Props) {
  const queryClient = useQueryClient()
  const [files, setFiles] = useState(initialFiles)
  const [urls, setUrls] = useState('')
  const config = useQuery({ queryKey: ['config'], queryFn: api.config, staleTime: Infinity })
  const webPages = config.data?.limits.max_web_pages
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['library'] })
  const add = useMutation({
    mutationFn: api.add,
    onSuccess: (result) => {
      setFiles([])
      setUrls('')
      // The library refreshes once the report is dismissed, else the first-run page would unmount it.
      if (result.duplicates.length || result.rejected.length) return
      refresh()
      onClose?.()
    },
  })
  const addFiles = (more: File[]) =>
    setFiles((f) => [
      ...f,
      ...more.filter((m) => !f.some((x) => x.name === m.name && x.size === m.size && x.lastModified === m.lastModified)),
    ])

  // In the dialog, files dropped outside the form (on the backdrop) are added too.
  useEffect(() => {
    if (!onClose) return
    const drop = (e: globalThis.DragEvent) => {
      const f = e.dataTransfer?.files
      if (f?.length) addFiles([...f])
    }
    window.addEventListener('drop', drop)
    return () => window.removeEventListener('drop', drop)
  }, [onClose])

  function submit(e: FormEvent) {
    e.preventDefault()
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    form.append('urls', urls.split(/\s+/).filter(Boolean).join('\n'))
    add.mutate(form)
  }

  // Drops here stay here; drops elsewhere in the app open the Add dialog (AppShell).
  function drop(e: DragEvent) {
    e.preventDefault()
    e.stopPropagation()
    addFiles([...e.dataTransfer.files])
  }

  if (add.data && (add.data.duplicates.length || add.data.rejected.length))
    return (
      <AddReport
        result={add.data}
        onMore={() => {
          add.reset()
          refresh()
        }}
        onDone={() => {
          refresh()
          onClose?.()
        }}
      />
    )

  const empty = !files.length && !urls.trim()
  return (
    <form onSubmit={submit} onDragOver={(e) => e.preventDefault()} onDrop={drop} className="min-w-0 space-y-4">
      <label className="flex cursor-pointer flex-col items-center gap-1 rounded-lg border-2 border-dashed border-muted-foreground/40 p-8 text-center hover:bg-muted/50 has-[:focus-visible]:border-ring has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50">
        <UploadIcon className="mb-1 size-6 text-muted-foreground" />
        <span className="font-medium pointer-coarse:hidden">Drop PDF or Word files here</span>
        <span className="hidden font-medium pointer-coarse:inline">Choose PDF or Word files</span>
        <span className="text-xs text-muted-foreground">
          <span className="pointer-coarse:hidden">or click to choose </span>(.pdf, .docx)
        </span>
        <input
          type="file"
          multiple
          accept=".pdf,.docx"
          className="sr-only"
          onChange={(e) => {
            addFiles([...(e.target.files ?? [])])
            e.target.value = ''
          }}
        />
      </label>
      {files.length > 0 && (
        <ul className="space-y-1 text-sm">
          {files.map((f) => (
            <li key={`${f.name}-${f.size}-${f.lastModified}`} className="flex items-center gap-2">
              <FileTextIcon className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">{f.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {f.size < 1e6 ? `${Math.max(1, Math.round(f.size / 1e3))} KB` : `${(f.size / 1e6).toFixed(1)} MB`}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={`Remove ${f.name}`}
                onClick={() => setFiles((all) => all.filter((x) => x !== f))}
              >
                <XIcon />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="space-y-1.5">
        <label htmlFor="add-urls" className="block text-sm font-medium">
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
          Web pages are saved just as they look in a browser, including images and content that loads as you scroll.
          {webPages && ` Up to ${webPages} pages each.`}
        </p>
      </div>
      {add.error && <Warning error>Could not add: {add.error.message}</Warning>}
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
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
function AddReport({ result, onMore, onDone }: { result: AddResult; onMore: () => void; onDone: () => void }) {
  const { added, duplicates, rejected } = result
  // Focused on mount so screen readers announce the report.
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => ref.current?.focus(), [])
  return (
    <div ref={ref} tabIndex={-1} className="min-w-0 space-y-4 text-sm wrap-anywhere outline-none">
      {added > 0 && (
        <p>
          Added {plural(added, 'document')}; {added === 1 ? 'it is' : 'they are'} processed in the background (see
          the{' '}
          <Link to="/library" className="underline" onClick={onDone}>
            library
          </Link>
          ).
        </p>
      )}
      {duplicates.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium">Already in your library</p>
          <ul className="space-y-1">
            {duplicates.map((d) => (
              <li key={d.id}>
                {stripScheme(d.title)} ({statusLabel(d.status)}) ·{' '}
                <Link to="/docs/$id" params={{ id: String(d.id) }} className="underline" onClick={onDone}>
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
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="outline" onClick={onMore}>
          Add more
        </Button>
        <Button onClick={onDone}>Done</Button>
      </div>
    </div>
  )
}
