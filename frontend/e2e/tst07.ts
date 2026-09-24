// TST-07 (R1): SHA-256 of every fixture source file is identical before and after the E2E suite.
import { createHash } from 'node:crypto'
import { readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const FIXTURES = resolve(import.meta.dirname, '../../.fixtures/synthetic')

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)]))
}

export function fixtureHashes(): Record<string, string> {
  return Object.fromEntries(walk(FIXTURES).sort().map((f) => [relative(FIXTURES, f), createHash('sha256').update(readFileSync(f)).digest('hex')]))
}

export const snapshotPath = () => join(process.env.E2E_WORKSPACE ?? '.', 'tst07-before.json')

export default function globalSetup() {
  writeFileSync(snapshotPath(), JSON.stringify(fixtureHashes()))
}
