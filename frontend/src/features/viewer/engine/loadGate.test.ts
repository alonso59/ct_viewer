// AUD-A5-13 (VW-14/15): an older load that resolves last is dropped; an aborted one throws.
import { LoadGate } from './loadGate'

const tick = (ms: number) => new Promise((r) => setTimeout(r, ms))

test('only the newest load may apply its result', async () => {
  const gate = new LoadGate()
  const applied: string[] = []
  const load = async (name: string, ms: number) => {
    const t = gate.begin()
    await tick(ms)
    if (t.check()) applied.push(name)
  }
  await Promise.all([load('old', 20), load('new', 1)])
  expect(applied).toEqual(['new'])
})

test('an aborted signal throws AbortError after the await', async () => {
  const gate = new LoadGate()
  const ac = new AbortController()
  const t = gate.begin(ac.signal)
  ac.abort()
  expect(t.live()).toBe(false)
  expect(() => t.check()).toThrow(expect.objectContaining({ name: 'AbortError' }))
})

test('a closed gate (disposed viewer) stops every ticket', () => {
  const gate = new LoadGate()
  const t = gate.begin()
  gate.close()
  expect(t.check()).toBe(false)
})
