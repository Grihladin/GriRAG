// The library query, shared by every view: the shell keeps it polling, the pages read documents from it.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Doc } from '@/api'

// The server says how often to poll: 2 s while something can be worked on, 30 s while only waiting, else stop.
export function useLibrary() {
  return useQuery({
    queryKey: ['library'],
    queryFn: api.library,
    refetchInterval: (query) => query.state.data?.poll_ms ?? false,
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

// Links show without their scheme: "en.wikipedia.org/wiki/PDF".
export const displayTitle = (d: { kind: Doc['kind']; title: string }) =>
  d.kind === 'url' ? d.title.replace(/^https?:\/\/(www\.)?/, '') : d.title
