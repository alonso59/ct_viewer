import { readFileSync } from 'node:fs'

import { fixtureHashes, snapshotPath } from './tst07'

export default function globalTeardown() {
  const before = JSON.parse(readFileSync(snapshotPath(), 'utf-8')) as Record<string, string>
  const after = fixtureHashes()
  const changed = Object.keys({ ...before, ...after }).filter((k) => before[k] !== after[k])
  if (changed.length) throw new Error(`TST-07: fixture sources changed during E2E (R1): ${changed.slice(0, 10).join(', ')}`)
}
