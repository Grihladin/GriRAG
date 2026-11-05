import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const backend = 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { proxy: { '/api': backend, '/files': backend } },
  // Served locally from disk, so big bundles are fine: the app (~600 kB) and the Research page (~800 kB, assistant-ui),
  // which main.tsx loads on first use.
  build: { chunkSizeWarningLimit: 900 },
})
