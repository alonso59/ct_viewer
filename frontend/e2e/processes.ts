// TST-22: wait for a test-owned process to exit, with bounded escalation and listener cleanup.
import type { ChildProcess } from 'node:child_process'

export async function stopProcess(child: ChildProcess, graceMs = 10_000): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return
  await new Promise<void>((resolve, reject) => {
    let deadline: ReturnType<typeof setTimeout>
    const cleanup = () => {
      clearTimeout(deadline)
      child.off('exit', exited)
      child.off('error', failed)
    }
    const exited = () => { cleanup(); resolve() }
    const failed = (error: Error) => { cleanup(); reject(error) }
    child.once('exit', exited)
    child.once('error', failed)
    deadline = setTimeout(() => {
      child.kill('SIGKILL')
      deadline = setTimeout(() => failed(new Error('Test-owned process did not exit after SIGKILL')), 5_000)
    }, graceMs)
    child.kill('SIGTERM')
  })
}
