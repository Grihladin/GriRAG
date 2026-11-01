import { useEffect, type RefObject } from 'react'

// The browser tab and history entries show what the page is about: "invoice total · GriRAG".
export function useTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · GriRAG`
  }, [title])
}

// "/" focuses the input from anywhere on the page, as on most search sites; not while typing in another field.
export function useSlashFocus(input: RefObject<HTMLInputElement | null>) {
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
  }, [input])
}
