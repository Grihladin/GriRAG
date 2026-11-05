import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

// A cited page in an answer ("S1"), shared by Ask and Research; opens the page viewer.
export function CitationChip({ className, ...props }: ComponentProps<'button'>) {
  return (
    <button
      type="button"
      className={cn(
        'relative ml-0.5 inline-flex h-5 items-center rounded-full border bg-muted px-1.5 align-text-bottom text-xs font-medium after:absolute after:inset-x-0 after:-inset-y-2.5 hover:border-transparent hover:bg-highlight-soft hover:text-highlight-foreground focus-visible:bg-highlight-soft focus-visible:text-highlight-foreground',
        className,
      )}
      {...props}
    />
  )
}
