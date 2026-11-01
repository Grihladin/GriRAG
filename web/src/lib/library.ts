// The library query, shared by every view: the shell keeps it polling, the pages read documents from it.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Doc } from '@/api'

// The server says how often to poll: 2 s while something can be worked on, 30 s while only waiting, else stop;
// every 5 s while it can't be reached.
export function useLibrary() {
  return useQuery({
    queryKey: ['library'],
    queryFn: api.library,
    refetchInterval: (query) => (query.state.status === 'error' ? 5000 : (query.state.data?.poll_ms ?? false)),
    refetchOnWindowFocus: true, // cheap, and catches changes made while polling was stopped
  })
}

export function useDocAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, kind }: { id: number; kind: 'retry' | 'delete' }) =>
      kind === 'retry' ? api.retry(id) : api.remove(id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['library'] }),
  })
}

export const isProcessing = (d: Doc) => d.status === 'working' || (d.status === 'queued' && !d.waiting)

export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

export const stripScheme = (t: string) => t.replace(/^https?:\/\/(www\.)?/, '')

// Links show without their scheme: "en.wikipedia.org/wiki/PDF".
export const displayTitle = (d: { kind: Doc['kind']; title: string }) =>
  d.kind === 'url' ? stripScheme(d.title) : d.title

// Web pages are captured as square screenshot tiles; links to PDF or Word files are downloaded and keep their page shape.
export const isCapture = (d: { kind: Doc['kind']; file_url: string | null }) =>
  d.kind === 'url' && !d.file_url?.endsWith('.pdf')

const labels: Record<Doc['status'], string> = { queued: 'Queued', working: 'Processing', done: 'Ready', error: 'Failed' }
export const statusLabel = (status: Doc['status']) => labels[status]

const kinds: Record<Doc['kind'], string> = { pdf: 'PDF', office: 'Word', url: 'Web page' }
export const kindLabel = (d: { kind: Doc['kind']; file_url: string | null }) =>
  d.kind === 'url' && !isCapture(d) ? 'Linked file' : kinds[d.kind]

export const fileLabel = (d: { kind: Doc['kind']; file_url: string | null }) =>
  isCapture(d) ? 'Full screenshot' : d.kind === 'pdf' ? 'Original file' : 'PDF version'
