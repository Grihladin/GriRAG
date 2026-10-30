import { useEffect } from 'react'

// The browser tab and history entries show what the page is about: "invoice total · PixelRAG".
export function useTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · PixelRAG`
  }, [title])
}
