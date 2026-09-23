import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev server proxies the API (docs/ops/DEV_ENV.md). Bind address via VITE_HOST; port and API
// target are overridable so parallel worktrees (and Playwright) can run side by side.
export default defineConfig({
  plugins: [react()],
  build: { target: 'es2022' },
  server: {
    host: process.env.VITE_HOST ?? '127.0.0.1',
    port: Number(process.env.VITE_PORT ?? 5173),
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000',
        // Node holds proxied response headers until the first body chunk; for the SSE stream
        // (API-40) that is the first ping, so flush them right away to report "live" at once.
        configure: (proxy) =>
          proxy.on('proxyRes', (proxyRes, _req, res) => {
            if (String(proxyRes.headers['content-type']).startsWith('text/event-stream')) setImmediate(() => res.flushHeaders())
          }),
      },
    },
  },
})
