import type { FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, type Hit } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

type Mode = 'search' | 'ask'

export function AskBox() {
  const run = useMutation({
    mutationFn: async ({ mode, q }: { mode: Mode; q: string }) =>
      mode === 'search' ? { mode, ...(await api.search(q)) } : { mode, ...(await api.ask(q)) },
  })

  // Enter submits with the first button (Search, the cheaper one); Ask is the second submit button.
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const submitter = (e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null
    const q = new FormData(e.currentTarget).get('q') as string
    run.mutate({ mode: submitter?.value === 'ask' ? 'ask' : 'search', q })
  }

  const data = run.data
  return (
    <Card>
      <CardContent className="space-y-4">
        <form onSubmit={submit} className="flex gap-2">
          <Input name="q" required placeholder="Ask or search your documents" className="flex-1" />
          <Button type="submit" value="search" variant="outline" disabled={run.isPending}>
            Search
          </Button>
          <Button type="submit" value="ask" disabled={run.isPending}>
            Ask
          </Button>
        </form>
        {run.isPending && <p className="text-sm text-muted-foreground">Working…</p>}
        {run.error && <p className="text-sm text-destructive">{run.error.message}</p>}
        {data?.message && <p className="text-sm text-muted-foreground">{data.message}</p>}
        {data?.mode === 'search' &&
          data.groups.map((g) => (
            <section key={g[0].doc_id} className="space-y-2">
              <div className="flex items-baseline gap-2">
                <a href={g[0].file_url} target="_blank" className="font-medium hover:underline">
                  {g[0].title}
                </a>
                {g[0].kind === 'url' && (
                  <a href={g[0].source} target="_blank" rel="noreferrer" className="text-sm text-muted-foreground hover:underline">
                    source
                  </a>
                )}
              </div>
              <Thumbs hits={g} caption={(h) => `p. ${h.page_no} · ${h.score.toFixed(2)}`} />
            </section>
          ))}
        {data?.mode === 'ask' && data.answer && (
          <section className="space-y-3">
            <p className="rounded-lg bg-muted p-3 whitespace-pre-wrap">{data.answer.text}</p>
            <p className="text-xs text-muted-foreground">Answered by {data.answer.model}</p>
            <h3 className="font-medium">Sources</h3>
            <Thumbs hits={data.answer.sources} caption={(h, i) => `S${i + 1} · ${h.title} p. ${h.page_no}`} />
          </section>
        )}
      </CardContent>
    </Card>
  )
}

function Thumbs({ hits, caption }: { hits: Hit[]; caption: (h: Hit, i: number) => string }) {
  return (
    <div className="flex flex-wrap gap-3">
      {hits.map((h, i) => (
        <figure key={h.image_url} className="w-[220px] space-y-1">
          <a href={h.image_url} target="_blank">
            <img src={h.image_url} width={220} loading="lazy" alt="" className="rounded-md border" />
          </a>
          <figcaption className="truncate text-xs text-muted-foreground" title={caption(h, i)}>
            {caption(h, i)}
          </figcaption>
        </figure>
      ))}
    </div>
  )
}
