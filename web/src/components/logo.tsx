// The GriRAG mark: a page outline that reads as a G. The gap on the right is the G's opening, the dog-ear is the
// accent. Drawn in the text colour, so it follows the theme; public/favicon.svg is the same mark on a graphite tile.
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="8 6 46 52" aria-hidden="true" className={className}>
      <path
        d="M38 13H22a5 5 0 0 0-5 5v28a5 5 0 0 0 5 5h20a5 5 0 0 0 5-5V35H34"
        fill="none"
        stroke="currentColor"
        strokeWidth="5.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M38 13v9h9z" className="fill-highlight stroke-highlight" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  )
}
