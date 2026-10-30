import type { ReactNode } from 'react'
import { CircleCheckIcon, CircleXIcon, ClockIcon, FileTextIcon, GlobeIcon } from 'lucide-react'
import type { Doc } from '@/api'
import { Progress } from '@/components/ui/progress'
import { Spinner } from '@/components/ui/spinner'

// Converting → Embedding k/n → Ready, or Queued, Waiting (rate limit) and Failed, with the server's message.
// clamp: the message is cut to 2 lines (library table); the document page shows it whole.
export function DocStatus({ doc: d, clamp = true }: { doc: Doc; clamp?: boolean }) {
  if (d.status === 'working' && d.page_count === null) return <Label icon={<Spinner />}>Converting</Label>
  if (d.status === 'working')
    return (
      <div className="w-40 space-y-1.5">
        <Label icon={<Spinner />}>
          Embedding {d.pages_embedded}/{d.page_count}
        </Label>
        <Progress value={(100 * d.pages_embedded) / d.page_count!} />
      </div>
    )
  if (d.status === 'done')
    return <Label icon={<CircleCheckIcon className="size-4 text-emerald-600 dark:text-emerald-500" />}>Ready</Label>
  const failed = d.status === 'error'
  return (
    <div className="space-y-0.5">
      {failed ? (
        <Label icon={<CircleXIcon className="size-4" />} className="text-destructive">
          Failed
        </Label>
      ) : (
        <Label icon={<ClockIcon className="size-4" />} className={d.waiting ? 'text-amber-700 dark:text-amber-400' : ''}>
          {d.waiting ? 'Waiting' : 'Queued'}
        </Label>
      )}
      {d.message && (
        <p className={`text-xs text-muted-foreground ${clamp ? 'line-clamp-2' : ''}`} title={d.message}>
          {d.message}
        </p>
      )}
    </div>
  )
}

function Label({ icon, className = '', children }: { icon: ReactNode; className?: string; children: ReactNode }) {
  return (
    <span className={`flex items-center gap-1.5 text-sm ${className}`}>
      {icon}
      {children}
    </span>
  )
}

export function KindIcon({ kind }: { kind: Doc['kind'] }) {
  const Icon = kind === 'url' ? GlobeIcon : FileTextIcon
  return <Icon className="size-4 shrink-0 text-muted-foreground" />
}
