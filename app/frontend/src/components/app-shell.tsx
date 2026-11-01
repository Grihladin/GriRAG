import { useCallback, useEffect, useState } from 'react'
import { Link, Outlet, useLocation } from '@tanstack/react-router'
import { CircleXIcon, ClockIcon, MoonIcon, PauseIcon, PlusIcon, SunIcon } from 'lucide-react'
import type { Doc } from '@/api'
import { AddPanel } from '@/components/add-panel'
import { ConfigMenu } from '@/components/config-menu'
import { Logo } from '@/components/logo'
import { Warning } from '@/components/warning'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Spinner } from '@/components/ui/spinner'
import { AddContext } from '@/lib/add-context'
import { isProcessing, useLibrary } from '@/lib/library'
import { toggleTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'

const navLink =
  'rounded-md px-2.5 py-1.5 whitespace-nowrap text-muted-foreground hover:text-foreground pointer-coarse:py-2.5 sm:px-3 data-[status=active]:bg-muted data-[status=active]:text-foreground'

// Top bar, worker banner and the routed page. The library query lives here so it keeps polling on every page.
export function AppShell() {
  const library = useLibrary()
  const docs = library.data?.docs ?? []
  const banner = library.error
    ? `Can't reach the GriRAG server (${library.error.message}). Is it running?`
    : library.data?.banner
  // `key` gives every opening a fresh form; files dropped anywhere arrive as `files`.
  const [add, setAdd] = useState({ open: false, key: 0, files: [] as File[] })
  const openAdd = useCallback(
    (files: File[] = []) => setAdd((a) => (a.open ? a : { open: true, key: a.key + 1, files })),
    [],
  )
  const closeAdd = useCallback(() => setAdd((a) => ({ ...a, open: false })), [])
  const dragging = useFileDrop(openAdd)
  const onDoc = useLocation({ select: (l) => l.pathname.startsWith('/docs/') })

  return (
    <AddContext value={openAdd}>
      <div className="flex min-h-screen flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-1.5 focus:ring-3 focus:ring-ring/50"
        >
          Skip to content
        </a>
        <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4 sm:gap-6 sm:px-6">
            <Link to="/" className="flex shrink-0 items-center gap-2 font-semibold">
              <Logo className="size-6" />
              <span className="text-[1.05rem] font-bold tracking-[-0.02em] max-sm:sr-only">GriRAG</span>
            </Link>
            <nav className="flex gap-1 text-sm">
              <Link to="/" className={navLink} activeOptions={{ exact: true, includeSearch: false }}>
                Ask
              </Link>
              <Link
                to="/library"
                className={cn(navLink, onDoc && 'bg-muted text-foreground')}
                aria-current={onDoc ? 'page' : undefined}
              >
                Library
              </Link>
            </nav>
            <div className="ml-auto flex items-center gap-1 sm:gap-4">
              <Activity docs={docs} paused={!!library.data?.banner} />
              <div className="flex items-center">
                <ConfigMenu />
                <ThemeButton />
              </div>
              <Button onClick={() => openAdd()}>
                <PlusIcon /> Add
              </Button>
            </div>
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
          {banner && (
            <Warning error={!!library.error} role="status" className="mb-6">
              {banner}
            </Warning>
          )}
          <Outlet />
        </main>
      </div>
      <Dialog open={add.open} onOpenChange={(open) => setAdd((a) => ({ ...a, open }))}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Add documents</DialogTitle>
          </DialogHeader>
          <AddPanel key={add.key} initialFiles={add.files} onClose={closeAdd} />
        </DialogContent>
      </Dialog>
      {dragging && (
        <div className="pointer-events-none fixed inset-2 z-[60] flex items-center justify-center rounded-xl border-2 border-dashed border-primary">
          <span className="rounded-full bg-primary px-4 py-1.5 text-sm text-primary-foreground">
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

// "2 processing · 1 waiting · 1 failed", linking to the library; nothing when all is done.
function Activity({ docs, paused }: { docs: Doc[]; paused: boolean }) {
  const processing = docs.filter(isProcessing).length
  const waiting = docs.filter((d) => d.waiting).length
  const failed = docs.filter((d) => d.status === 'error').length
  if (!processing && !waiting && !failed) return null
  return (
    <Link
      to="/library"
      className="hidden items-center gap-3 text-sm whitespace-nowrap text-muted-foreground hover:text-foreground md:flex"
    >
      {processing > 0 && (
        <span className="flex items-center gap-1.5">
          {paused ? <PauseIcon className="size-4" /> : <Spinner />} {processing} {paused ? 'on hold' : 'processing'}
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

function ThemeButton() {
  return (
    <Button
      variant="ghost"
      size="icon"
      title="Switch light/dark theme"
      aria-label="Switch light/dark theme"
      onClick={toggleTheme}
    >
      <SunIcon className="dark:hidden" />
      <MoonIcon className="hidden dark:block" />
    </Button>
  )
}
