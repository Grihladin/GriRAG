import type { ReactNode } from 'react'
import { CircleXIcon, TriangleAlertIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription } from '@/components/ui/alert'

// Amber notice for things that are not the user's fault (worker paused, rate limits, refused actions);
// red with error, for failures.
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
          ? 'border-red-300 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200'
          : 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200',
        className,
      )}
    >
      <Icon />
      <AlertDescription className="text-inherit">{children}</AlertDescription>
    </Alert>
  )
}
