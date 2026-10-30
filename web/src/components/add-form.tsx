import type { FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type AddResult } from '@/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

export function AddForm() {
  const queryClient = useQueryClient()
  const add = useMutation({
    mutationFn: api.add,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['library'] }),
  })

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    add.mutate(new FormData(form), { onSuccess: () => form.reset() })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <form onSubmit={submit} className="flex flex-wrap items-start gap-3">
          <Input type="file" name="files" multiple accept=".pdf,.docx" className="w-72" />
          <Textarea name="urls" placeholder="Links, one per line" className="min-h-9 flex-1" rows={1} />
          <Button type="submit" disabled={add.isPending}>
            {add.isPending ? 'Adding…' : 'Add'}
          </Button>
        </form>
        {add.data && <AddNotice result={add.data} />}
        {add.error && (
          <Alert variant="destructive">
            <AlertDescription>{add.error.message}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  )
}

function AddNotice({ result }: { result: AddResult }) {
  const { added, duplicates, rejected } = result
  if (!added && !duplicates.length && !rejected.length) return null
  return (
    <Alert>
      <AlertDescription>
        {added > 0 && <p>Added {added}.</p>}
        {duplicates.map((d) => (
          <p key={d.id}>
            {d.title} is already in the library as #{d.id} ({d.status}); delete it first to refresh.
          </p>
        ))}
        {rejected.map((r) => (
          <p key={r} className="text-destructive">
            Rejected {r}
          </p>
        ))}
      </AlertDescription>
    </Alert>
  )
}
