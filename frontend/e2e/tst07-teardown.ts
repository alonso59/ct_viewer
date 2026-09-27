import { readFileSync, rmSync } from 'node:fs'

import { createdDirs } from './servers'
import { fixtureHashes, snapshotPath } from './tst07'

export default function globalTeardown() {
  try {
    const before = JSON.parse(readFileSync(snapshotPath(), 'utf-8')) as Record<string, string>
    const after = fixtureHashes()
    const changed = Object.keys({ ...before, ...after }).filter((k) => before[k] !== after[k])
    if (changed.length) throw new Error(`TST-07: fixture sources changed during E2E (R1): ${changed.slice(0, 10).join(', ')}`)
  } finally {
    // AUD-A0-05: the temp workspace, derived and plugins folders this run created go, unless kept
    if (!process.env.E2E_KEEP) for (const dir of createdDirs()) rmSync(dir, { recursive: true, force: true })
  }
}
