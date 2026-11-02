// TST-05: the E2E web server proxies to the E2E API in both modes, and lane ports are refused.
import { afterEach, describe, expect, it, vi } from 'vitest'

const dirs = { workspace: '/w', derived: '/d', datasets: '/s', plugins: '/p' }
const env = { ...process.env }
afterEach(() => {
  process.env = { ...env }
  vi.resetModules()
})

async function webCommand(build: boolean): Promise<string> {
  process.env.E2E_API_PORT = '8155'
  process.env.E2E_WEB_PORT = '5315'
  if (build) process.env.E2E_BUILD = '1'
  else delete process.env.E2E_BUILD
  const { serverCommands } = await import('../../e2e/servers')
  return serverCommands(dirs).find((c) => c.name === 'web')?.command ?? ''
}

describe('E2E web server', () => {
  it.each([false, true])('every command of the chain gets the E2E API proxy (build: %s)', async (build) => {
    const cmd = await webCommand(build)
    expect(cmd.startsWith('export VITE_PORT=5315 VITE_API_PROXY=http://127.0.0.1:8155 && ')).toBe(true)
    if (build) expect(cmd).toContain('&& npx vite preview')
  })

  it('refuses a dev-lane port', async () => {
    process.env.E2E_API_PORT = '8000'
    await expect(import('../../e2e/servers')).rejects.toThrow(/collide with a dev lane/)
  })
})
