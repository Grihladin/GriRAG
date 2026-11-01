import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { SlidersHorizontalIcon } from 'lucide-react'
import { api, type Config } from '@/api'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'

// "muse-spark-1.3-contributor" from "meta/muse-spark-1.3-contributor".
const shortName = (model: string) => model.split('/').pop() ?? model

// Header button with the answer model's name; opens the settings that shape answers and search (read-only, from .env).
export function ConfigMenu() {
  const config = useQuery({ queryKey: ['config'], queryFn: api.config, staleTime: Infinity })
  const model = config.data?.answer.model
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" className="max-w-56 text-muted-foreground" aria-label="Models and settings">
          <SlidersHorizontalIcon />
          {model && <span className="truncate max-lg:hidden">{shortName(model)}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="max-h-[calc(100vh-5rem)] w-[min(22rem,calc(100vw-2rem))] overflow-y-auto p-0">
        <h2 className="px-4 pt-4 font-heading text-lg font-semibold tracking-[-0.01em]">Models and settings</h2>
        {config.data ? (
          <Settings c={config.data} />
        ) : config.isError ? (
          <p className="px-4 py-3 text-sm text-destructive">Can't load the settings ({config.error.message}).</p>
        ) : (
          <div className="space-y-2 p-4">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        )}
        <p className="border-t px-4 py-3 text-xs text-muted-foreground">
          Set in <code>.env</code>. Restart the app to apply a change; a new embedding model also needs{' '}
          <code>make reembed</code>.
        </p>
      </PopoverContent>
    </Popover>
  )
}

function Settings({ c }: { c: Config }) {
  const n = (v: number) => v.toLocaleString('en')
  return (
    <div className="divide-y">
      <Group title="Answers" model={c.answer.model}>
        <Row label="Temperature">{c.answer.temperature}</Row>
        <Row label="Reasoning effort">{c.answer.reasoning_effort ?? 'off'}</Row>
        <Row label="Pages read per answer">{c.answer.pages}</Row>
        <Row label="Longest answer">{n(c.answer.max_tokens)} tokens</Row>
      </Group>
      <Group title="Search index" model={c.embedding.model}>
        <Row label="Pages per request">{c.embedding.batch_pages}</Row>
        <Row label="Query type">{c.embedding.query_type}</Row>
        <Row label="Page input">{c.embedding.passage_mode}</Row>
      </Group>
      <Group title="Page images">
        <Row label="Longest edge">{n(c.pages.longest_edge_px)} px</Row>
        <Row label="JPEG quality">{c.pages.jpeg_quality}</Row>
        <Row label="Web page slices">
          {n(c.pages.web_viewport_width)} × {n(c.pages.web_slice_height)} px
        </Row>
      </Group>
      <Group title="Limits">
        <Row label="Pages per document">{n(c.limits.max_pages)}</Row>
        <Row label="Slices per web page">{n(c.limits.max_web_pages)}</Row>
        <Row label="Upload size">{n(c.limits.max_upload_mb)} MB</Row>
      </Group>
    </div>
  )
}

function Group({ title, model, children }: { title: string; model?: string; children: ReactNode }) {
  return (
    <section className="space-y-2 px-4 py-3">
      <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
      {model && <p className="text-[0.95rem] font-medium wrap-anywhere text-foreground">{model}</p>}
      <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">{children}</dl>
    </section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium tabular-nums">{children}</dd>
    </>
  )
}
