import { useCallback, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, Outlet } from '@tanstack/react-router'
import { CircleXIcon, ClockIcon, MonitorIcon, MoonIcon, PlusIcon, SunIcon } from 'lucide-react'
import { api, type Doc } from '@/api'
import { AddPanel } from '@/components/add-panel'
import { Warning } from '@/components/warning'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Spinner } from '@/components/ui/spinner'
import { AddContext } from '@/lib/add-context'
import { isProcessing, useLibrary } from '@/lib/library'
import { getTheme, setTheme, type Theme } from '@/lib/theme'

const navLink = 'rounded-md px-3 py-1.5 text-muted-foreground hover:text-foreground'
const navActive = { className: 'bg-muted text-foreground' }

// Top bar, worker banner and the routed page. The library query lives here so it keeps polling on every page.
export function AppShell() {
  const library = useLibrary()
  const quota = useQuery({ queryKey: ['quota'], queryFn: api.quota })
  const docs = library.data?.docs ?? []
  const banner = library.error
    ? `Can't reach the PixelRAG server (${library.error.message}). Is it running?`
    : library.data?.banner
  // `key` gives every opening a fresh form; files dropped anywhere arrive as `files`.
  const [add, setAdd] = useState({ open: false, key: 0, files: [] as File[] })
  const openAdd = useCallback(
    (files: File[] = []) => setAdd((a) => (a.open ? a : { open: true, key: a.key + 1, files })),
    [],
  )
  const dragging = useFileDrop(openAdd)

  return (
    <AddContext value={openAdd}>
      <div className="flex min-h-screen flex-col">
        <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-6">
            <Link to="/" className="flex items-center gap-2 font-semibold">
              <img src="/favicon.svg" alt="" className="size-6" />
              PixelRAG
            </Link>
            <nav className="flex gap-1 text-sm">
              <Link to="/" className={navLink} activeProps={navActive} activeOptions={{ exact: true, includeSearch: false }}>
                Ask
              </Link>
              <Link to="/library" className={navLink} activeProps={navActive}>
                Library {docs.length > 0 && <span className="text-muted-foreground">{docs.length}</span>}
              </Link>
            </nav>
            <div className="ml-auto flex items-center gap-4">
              <Activity docs={docs} />
              {quota.data?.quota && <span className="text-xs text-muted-foreground">{quota.data.quota}</span>}
              <ThemeButton />
              <Button onClick={() => openAdd()}>
                <PlusIcon /> Add
              </Button>
            </div>
          </div>
        </header>
        {banner && (
          <div className="mx-auto w-full max-w-6xl px-6 pt-4">
            <Warning>{banner}</Warning>
          </div>
        )}
        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-6">
          <Outlet />
        </main>
      </div>
      <Dialog open={add.open} onOpenChange={(open) => setAdd((a) => ({ ...a, open }))}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Add documents</DialogTitle>
          </DialogHeader>
          <AddPanel key={add.key} initialFiles={add.files} onClose={() => setAdd((a) => ({ ...a, open: false }))} />
        </DialogContent>
      </Dialog>
      {dragging && (
        <div className="pointer-events-none fixed inset-2 z-[60] flex justify-center rounded-xl border-2 border-dashed border-primary">
          <span className="mt-4 h-fit rounded-full bg-primary px-4 py-1.5 text-sm text-primary-foreground">
            Drop PDF or Word files to add them
          </span>
        </div>
      )}
    </AddContext>
  )
}

// Files dragged over the window: show the outline; a drop not handled by a drop zone calls onDrop.
function useFileDrop(onDrop: (files: File[]) => void) {
  const [dragging, setDragging] = useState(false)
  useEffect(() => {
    let depth = 0
    const hasFiles = (e: DragEvent) => !!e.dataTransfer?.types.includes('Files')
    const enter = (e: DragEvent) => {
      if (hasFiles(e) && depth++ === 0) setDragging(true)
    }
    const leave = (e: DragEvent) => {
      if (hasFiles(e) && --depth === 0) setDragging(false)
    }
    const over = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault() // else the browser opens the file instead of dropping it
    }
    const end = () => {
      depth = 0
      setDragging(false)
    }
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      onDrop([...e.dataTransfer!.files])
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragleave', leave)
    window.addEventListener('dragover', over)
    window.addEventListener('drop', end, true) // capture: runs even when a drop zone stops the event
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('dragover', over)
      window.removeEventListener('drop', end, true)
      window.removeEventListener('drop', drop)
    }
  }, [onDrop])
  return dragging
}

// "Processing 2 · 1 waiting · 1 failed", linking to the library; nothing when all is done.
function Activity({ docs }: { docs: Doc[] }) {
  const processing = docs.filter(isProcessing).length
  const waiting = docs.filter((d) => d.waiting).length
  const failed = docs.filter((d) => d.status === 'error').length
  if (!processing && !waiting && !failed) return null
  return (
    <Link to="/library" className="flex items-center gap-3 text-sm text-muted-foreground hover:text-foreground">
      {processing > 0 && (
        <span className="flex items-center gap-1.5">
          <Spinner /> Processing {processing}
        </span>
      )}
      {waiting > 0 && (
        <span className="flex items-center gap-1.5">
          <ClockIcon className="size-4" /> {waiting} waiting
        </span>
      )}
      {failed > 0 && (
        <span className="flex items-center gap-1.5 text-destructive">
          <CircleXIcon className="size-4" /> {failed} failed
        </span>
      )}
    </Link>
  )
}

const themes: { value: Theme; label: string; Icon: typeof SunIcon }[] = [
  { value: 'system', label: 'System theme', Icon: MonitorIcon },
  { value: 'light', label: 'Light theme', Icon: SunIcon },
  { value: 'dark', label: 'Dark theme', Icon: MoonIcon },
]

// Cycles system → light → dark.
function ThemeButton() {
  const [theme, set] = useState(getTheme)
  const i = themes.findIndex((t) => t.value === theme)
  const { label, Icon } = themes[i]
  const next = themes[(i + 1) % themes.length].value
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      title={`${label} (click to change)`}
      aria-label={label}
      onClick={() => {
        setTheme(next)
        set(next)
      }}
    >
      <Icon />
    </Button>
  )
}
