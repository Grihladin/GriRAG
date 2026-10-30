import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AppShell } from '@/components/app-shell'
import { AskBox } from '@/components/ask-box'
import { LibraryTable } from '@/components/library-table'
import './index.css'

const rootRoute = createRootRoute({ component: AppShell })
const askRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', component: AskBox })
const libraryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/library',
  component: LibraryTable,
})
const docRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/docs/$id',
  component: () => <p>Document #{docRoute.useParams().id}</p>,
})
const router = createRouter({ routeTree: rootRoute.addChildren([askRoute, libraryRoute, docRoute]) })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

// Interactive requests cost money and are never retried automatically (PLAN.md §6.2).
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
