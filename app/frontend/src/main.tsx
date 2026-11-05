import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRootRoute, createRoute, createRouter, lazyRouteComponent, RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AppShell } from '@/components/app-shell'
import { AskPage } from '@/components/ask-page'
import { DocPage } from '@/components/doc-page'
import { LibraryPage } from '@/components/library-page'
import './index.css'

const rootRoute = createRootRoute({ component: AppShell })
const askRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: AskPage,
  validateSearch: (s: Record<string, unknown>): { q?: string } => ({
    q: typeof s.q === 'string' && s.q.trim() ? s.q : undefined,
  }),
})
// t: the conversation (a thread id the page makes up); q: a first question, sent once, from the Ask box.
// Loaded on first use: assistant-ui is most of the UI's code.
const researchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/research',
  component: lazyRouteComponent(() => import('@/components/research-page'), 'ResearchPage'),
  validateSearch: (s: Record<string, unknown>): { t?: string; q?: string } => ({
    t: typeof s.t === 'string' && s.t ? s.t : undefined,
    q: typeof s.q === 'string' && s.q.trim() ? s.q : undefined,
  }),
})
const libraryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/library',
  component: LibraryPage,
})
const docRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/docs/$id',
  component: DocPage,
  validateSearch: (s: Record<string, unknown>): { page?: number } => {
    const page = Number(s.page)
    return Number.isInteger(page) && page > 0 ? { page } : {}
  },
})
const router = createRouter({ routeTree: rootRoute.addChildren([askRoute, researchRoute, libraryRoute, docRoute]) })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

// Interactive requests cost money and are never retried automatically.
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
