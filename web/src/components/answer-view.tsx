import { useState } from 'react'
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

// Styles for the elements Markdown produces; the theme has no typography plugin.
const prose =
  'space-y-3 leading-7 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:font-mono [&_code]:text-sm [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:mt-1 [&_ol]:list-decimal [&_ol]:pl-6 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-muted [&_pre]:p-3 [&_strong]:font-semibold [&_ul]:list-disc [&_ul]:pl-6'

export function AnswerView({ answer, onOpen }: { answer: Answer; onOpen: (p: ViewerPage) => void }) {
  const [hovered, setHovered] = useState<number | null>(null)
  const open = (n: number) => {
    const s = answer.sources[n - 1]
    if (s) onOpen({ docId: s.doc_id, page: s.page_no, label: `S${n}` })
  }

  return (
    <div className="space-y-6">
      <div className={prose}>
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
              return (
                <button
                  type="button"
                  title={answer.sources[n - 1] && `${displayTitle(answer.sources[n - 1])}, page ${answer.sources[n - 1].page_no}`}
                  onClick={() => open(n)}
                  onMouseEnter={() => setHovered(n)}
                  onMouseLeave={() => setHovered(null)}
                  className="mx-0.5 inline-flex h-5 items-center rounded-full border bg-muted px-1.5 align-text-bottom text-xs font-medium hover:bg-primary hover:text-primary-foreground"
                >
                  {children}
                </button>
              )
            },
          }}
        >
          {linkCitations(answer.text)}
        </Markdown>
      </div>
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-muted-foreground">Sources</h2>
        <div className="flex flex-wrap gap-4">
          {answer.sources.map((h, i) => (
            <PageThumb
              key={h.image_url}
              hit={h}
              label={`S${i + 1}`}
              caption={`S${i + 1} · ${displayTitle(h)} · p. ${h.page_no} · ${h.score.toFixed(2)}`}
              highlight={hovered === i + 1}
              onOpen={onOpen}
            />
          ))}
        </div>
      </section>
    </div>
  )
}
