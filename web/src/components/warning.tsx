import type { ReactNode } from 'react'
import { TriangleAlertIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription } from '@/components/ui/alert'

// Amber notice for things that are not the user's fault: worker paused, rate limits, refused actions.
export function Warning({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <Alert
      className={cn(
        'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200',
        className,
      )}
    >
      <TriangleAlertIcon />
      <AlertDescription className="text-inherit">{children}</AlertDescription>
    </Alert>
  )
}
