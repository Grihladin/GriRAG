import { useMemo, useState } from 'react'
import Markdown from 'react-markdown'
import type { AskResult } from '@/api'
import type { ViewerPage } from '@/components/page-viewer'
import { PageThumb } from '@/components/search-results'
import { displayTitle } from '@/lib/library'

type Answer = NonNullable<AskResult['answer']>

// [S1], [S1, S3] and [S1][S2] become Markdown links #cite-N, which render as buttons for the page viewer.
const citations = /\[(S\d+(?:\s*,\s*S\d+)*)\]/g
const linkCitations = (text: string) =>
  text.replace(citations, (_, labels: string) =>
    labels
      .split(/\s*,\s*/)
      .map((l) => `[${l}](#cite-${l.slice(1)})`)
      .join(' '),
  )

// The S-numbers the answer cites that exist, e.g. "[S3] … [S1, S3] … [S9]" with 8 sources → {1, 3}.
const citedNumbers = (text: string, count: number) =>
  new Set(
    [...text.matchAll(citations)]
      .flatMap((m) => m[1].split(/\s*,\s*/))
      .map((l) => Number(l.slice(1)))
      .filter((n) => n >= 1 && n <= count),
  )

// Styles for the elements Markdown produces; the theme has no typography plugin.
const prose =
  'max-w-[72ch] space-y-3 text-base leading-7 wrap-break-word [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:font-mono [&_code]:text-sm [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:mt-1 [&_ol]:list-decimal [&_ol]:pl-6 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-muted [&_pre]:p-3 [&_strong]:font-semibold [&_ul]:list-disc [&_ul]:pl-6'

export function AnswerView({ answer, onOpen }: { answer: Answer; onOpen: (p: ViewerPage) => void }) {
  const [hovered, setHovered] = useState<number | null>(null)
  // Only the cited pages are shown; with no valid citation, every page the model read.
  const cited = useMemo(() => citedNumbers(answer.text, answer.sources.length), [answer])
  const shown = answer.sources.map((h, i) => ({ h, n: i + 1 })).filter(({ n }) => !cited.size || cited.has(n))

  // Memoised so that highlighting a source on hover or focus does not re-create the citation buttons (and drop focus).
  const text = useMemo(
    () => (
      <Markdown
        components={{
          a: ({ href, children }) => {
            const n = Number(href?.match(/^#cite-(\d+)$/)?.[1])
            if (!n)
              return (
                <a href={href} target="_blank" rel="noreferrer" className="underline">
                  {children}
                </a>
              )
            const s = answer.sources[n - 1]
            if (!s) return <span className="text-muted-foreground">[S{n}]</span>
            return (
              <button
                type="button"
                title={`${displayTitle(s)}, page ${s.page_no}`}
                onClick={() => onOpen({ docId: s.doc_id, page: s.page_no, label: `S${n}` })}
                onMouseEnter={() => setHovered(n)}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setHovered(n)}
                onBlur={() => setHovered(null)}
                className="relative ml-0.5 inline-flex h-5 items-center rounded-full border bg-muted px-1.5 align-text-bottom text-xs font-medium after:absolute after:inset-x-0 after:-inset-y-2.5 hover:border-transparent hover:bg-highlight-soft hover:text-highlight-foreground focus-visible:bg-highlight-soft focus-visible:text-highlight-foreground"
              >
                {children}
              </button>
            )
          },
        }}
      >
        {linkCitations(answer.text)}
      </Markdown>
    ),
    [answer, onOpen],
  )

  return (
    <div className="space-y-6">
      <div className={prose}>{text}</div>
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-muted-foreground">{cited.size ? 'Sources' : 'Pages read'}</h2>
        <div className="grid grid-cols-2 items-start gap-3 sm:flex sm:flex-wrap">
          {shown.map(({ h, n }) => (
            <PageThumb
              key={h.image_url}
              hit={h}
              label={cited.size ? `S${n}` : undefined}
              caption={`${cited.size ? `S${n} · ` : ''}${displayTitle(h)} · p. ${h.page_no} · ${h.score.toFixed(2)}`}
              highlight={hovered === n}
              onOpen={onOpen}
            />
          ))}
        </div>
      </section>
    </div>
  )
}
