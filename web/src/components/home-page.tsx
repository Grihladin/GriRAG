import { useQuery } from '@tanstack/react-query'
import { api } from '@/api'
import { AddForm } from '@/components/add-form'
import { AskBox } from '@/components/ask-box'
import { LibraryTable } from '@/components/library-table'

export function HomePage() {
  const quota = useQuery({ queryKey: ['quota'], queryFn: api.quota })
  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="flex items-baseline justify-between gap-4">
        <h1 className="text-xl font-semibold">PixelRAG (personal)</h1>
        {quota.data?.quota && <span className="text-sm text-muted-foreground">{quota.data.quota}</span>}
      </header>
      <AddForm />
      <AskBox />
      <LibraryTable />
    </main>
  )
}
