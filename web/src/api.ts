// Types and calls for the FastAPI JSON API (app/main.py). User-facing errors arrive as `message` in a 200.

export type Doc = {
  id: number
  kind: 'pdf' | 'office' | 'url'
  source: string
  title: string
  status: 'queued' | 'working' | 'done' | 'error'
  message: string | null
  warning: string | null
  page_count: number | null
  pages_embedded: number
  waiting: boolean
  file_url: string | null // the whole document (doc.pdf or source.jpg); null until it exists
}

export type Library = { docs: Doc[]; banner: string | null; poll_ms: number | null }

export type AddResult = {
  added: number
  duplicates: { id: number; title: string; status: Doc['status'] }[]
  rejected: string[]
}

export type Hit = {
  doc_id: number
  page_no: number
  score: number
  title: string
  kind: Doc['kind']
  source: string
  file_url: string
  image_url: string
}

export type SearchResult = { groups: Hit[][]; message: string | null }
export type AskResult = {
  answer: { text: string; model: string; sources: Hit[] } | null
  groups: Hit[][] // every matching page, as in SearchResult
  message: string | null
}

export const pageUrl = (docId: number, page: number) => `/files/${docId}/pages/${String(page).padStart(4, '0')}.jpg`

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

const post = (body: unknown) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  library: () => call<Library>('/api/library'),
  quota: () => call<{ quota: string | null }>('/api/quota'),
  add: (form: FormData) => call<AddResult>('/api/add', { method: 'POST', body: form }),
  search: (q: string) => call<SearchResult>(`/api/search?q=${encodeURIComponent(q)}`),
  ask: (q: string) => call<AskResult>('/api/ask', post({ q })),
  retry: (id: number) => call<{ message: string | null }>(`/api/docs/${id}/retry`, { method: 'POST' }),
  remove: (id: number) => call<{ message: string | null }>(`/api/docs/${id}`, { method: 'DELETE' }),
}
