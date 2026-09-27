import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import type { Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

const here = dirname(fileURLToPath(import.meta.url))

// Vitest empties every CSS import (also `?raw`); `?cssraw` gives a test the stylesheet text instead,
// for the token and colour checks of theme/tokens.test.ts (UI-11)
const cssRaw = (): Plugin => ({
  name: 'css-raw',
  enforce: 'pre',
  resolveId(source, importer) {
    if (!source.endsWith('.css?cssraw')) return null
    const file = source.slice(0, -'?cssraw'.length)
    const abs = file.startsWith('/src/') ? resolve(here, `.${file}`) : resolve(importer ? dirname(importer) : here, file)
    // the virtual id must not end in `.css`, or Vitest's CSS handling empties it again
    return `\0cssraw:${abs}.js`
  },
  load(id) {
    if (!id.startsWith('\0cssraw:')) return null
    return `export default ${JSON.stringify(readFileSync(id.slice('\0cssraw:'.length, -'.js'.length), 'utf8'))}`
  },
})

export default defineConfig({
  plugins: [react(), cssRaw()],
  test: {
    environment: 'node',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    env: { VITE_API_MODE: 'mock' },
  },
})
