import type { ReactNode } from 'react'
import { CircleXIcon, TriangleAlertIcon } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { cn } from '@/lib/utils'

// Neutral notice for things that are not the user's fault (worker paused, rate limits, refused actions);
// the error red only with `error`, for failures.
export function Warning({
  children,
  className,
  error,
  role = 'alert',
}: {
  children: ReactNode
  className?: string
  error?: boolean
  role?: 'alert' | 'status'
}) {
  const Icon = error ? CircleXIcon : TriangleAlertIcon
  return (
    <Alert
      role={role}
      className={cn(
        error
          ? 'border-destructive/30 bg-destructive/5 text-destructive dark:bg-destructive/10'
          : 'border-border bg-card text-foreground [&>svg]:text-muted-foreground',
        className,
      )}
    >
      <Icon />
      <AlertDescription className="text-inherit">{children}</AlertDescription>
    </Alert>
  )
}
