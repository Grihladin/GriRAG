import type { ReactNode } from 'react'
import { ExternalLinkIcon } from 'lucide-react'

// A link that opens in a new tab, with the icon and the screen-reader hint that say so.
export function ExternalLink({ href, className, children }: { href: string; className?: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {children} <ExternalLinkIcon className="size-3.5" />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  )
}
