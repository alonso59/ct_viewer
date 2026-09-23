import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev server proxies the API (docs/ops/DEV_ENV.md). Bind address via VITE_HOST.
export default defineConfig({
  plugins: [react()],
  server: {
    host: process.env.VITE_HOST ?? '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
