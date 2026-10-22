// TST-22: process teardown waits for exit, escalates a test-owned worker and is idempotent.
import { spawn } from 'node:child_process'
import { once } from 'node:events'

import { describe, expect, it } from 'vitest'

import { stopProcess } from '../../e2e/processes'

describe('TST-22 browser runner teardown', () => {
  it.each([false, true])('reaps a child (ignores TERM: %s)', async (ignoreTerm) => {
    const child = spawn(process.execPath, ['-e', `${ignoreTerm ? "process.on('SIGTERM', () => {});" : ''} process.send('ready'); setInterval(() => {}, 1000)`], { stdio: ['ignore', 'ignore', 'pipe', 'ipc'] })
    try {
      await once(child, 'message')
      await stopProcess(child, 50)
      expect(child.exitCode !== null || child.signalCode !== null).toBe(true)
      await stopProcess(child, 50)
    } finally {
      if (child.exitCode === null && child.signalCode === null) {
        const exited = once(child, 'exit')
        child.kill('SIGKILL')
        await exited
      }
      child.stderr?.destroy()
    }
  })
})
