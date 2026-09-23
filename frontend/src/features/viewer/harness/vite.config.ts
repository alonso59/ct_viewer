/// <reference types="node" />
// Standalone viewer harness (P3 manual testing + TST-09 bench). Does not touch the app router.
//   npx vite --config src/features/viewer/harness/vite.config.ts
//   → http://127.0.0.1:5175/  (redirects to the harness page)
// `/files/*` serves the repo's `.fixtures/` (synthetic fixtures + the reference volume) with
// Content-Length so the loading bar has byte progress; `/api` is proxied like the app.
import { createReadStream, statSync } from 'node:fs'
import { resolve } from 'node:path'

import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

const frontend = resolve(__dirname, '../../../..')
const fixtures = resolve(frontend, '../.fixtures')
const PAGE = '/src/features/viewer/harness/index.html'

function files(): Plugin {
  return {
    name: 'viewer-harness-files',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = decodeURIComponent((req.url ?? '').split('?')[0] ?? '')
        if (url === '/') {
          res.writeHead(302, { Location: PAGE })
          res.end()
          return
        }
        if (!url.startsWith('/files/')) return next()
        const path = resolve(fixtures, url.slice('/files/'.length))
        if (!path.startsWith(fixtures)) {
          res.statusCode = 403
          res.end()
          return
        }
        let size: number
        try {
          size = statSync(path).size
        } catch {
          res.writeHead(404, { 'Content-Type': 'application/problem+json' })
          res.end(JSON.stringify({ type: 'not-found', title: 'File not found', status: 404 }))
          return
        }
        res.writeHead(200, { 'Content-Type': 'application/octet-stream', 'Content-Length': size, 'Cache-Control': 'no-store' })
        createReadStream(path).pipe(res)
      })
    },
  }
}

export default defineConfig({
  root: frontend,
  plugins: [react(), files()],
  server: {
    host: process.env.VITE_HOST ?? '127.0.0.1',
    port: Number(process.env.HARNESS_PORT ?? 5175),
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
