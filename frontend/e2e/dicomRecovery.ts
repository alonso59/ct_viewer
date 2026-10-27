// TST-24: the browser gets a private API; the shared E2E server and other jobs stay alive.
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { createWriteStream, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { createServer, request } from 'node:http'
import type { AddressInfo } from 'node:net'
import { join, resolve } from 'node:path'

import { expect } from '@playwright/test'

import { WEB } from './helpers'
import { stopProcess } from './processes'

export async function startRecoveryServer(root: string) {
  mkdirSync(root, { recursive: true, mode: 0o700 })
  writeFileSync(join(root, 'pause'), '')
  const reservation = createServer()
  reservation.listen(0, '127.0.0.1')
  await once(reservation, 'listening')
  const apiPort = (reservation.address() as AddressInfo).port
  const webPort = Number(new URL(WEB).port)
  const proxy = createServer((incoming, outgoing) => {
    const forwarded = request({
      hostname: '127.0.0.1', port: incoming.url?.startsWith('/api/') ? apiPort : webPort,
      method: incoming.method, path: incoming.url, headers: incoming.headers,
    }, (response) => {
      outgoing.writeHead(response.statusCode ?? 502, response.headers)
      response.on('error', () => outgoing.destroy())
      response.pipe(outgoing)
    })
    forwarded.on('error', () => {
      if (!outgoing.headersSent) outgoing.writeHead(502)
      outgoing.end()
    })
    outgoing.on('close', () => forwarded.destroy())
    incoming.pipe(forwarded)
  })
  proxy.listen(0, '127.0.0.1')
  await once(proxy, 'listening')
  reservation.close()
  await once(reservation, 'close')
  const url = `http://127.0.0.1:${(proxy.address() as AddressInfo).port}`
  const backend = resolve(import.meta.dirname, '../../backend')
  const python = resolve(backend, process.env.E2E_PYTHON ?? '.venv/bin/python')
  const log = createWriteStream(join(root, 'api.log'), { flags: 'a' })
  const env = {
    ...process.env, PYTHONPATH: `${backend}:${resolve(backend, '..')}`, PYTHONDONTWRITEBYTECODE: '1',
    OMP_NUM_THREADS: '1', OPENBLAS_NUM_THREADS: '1', MKL_NUM_THREADS: '1', ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS: '1',
  }
  const launch = () => {
    const process = spawn(python, ['-m', 'tests.dicom_browser_server', root, String(apiPort), url], { cwd: backend, env, stdio: ['ignore', 'pipe', 'pipe'] })
    process.stdout.pipe(log, { end: false })
    process.stderr.pipe(log, { end: false })
    return process
  }
  let apiProcess = launch()
  const ready = async () => {
    await expect.poll(async () => {
      expect(apiProcess.exitCode).toBeNull()
      try { return (await fetch(`${url}/api/v1/health`)).ok } catch { return false }
    }, { timeout: 45_000 }).toBe(true)
  }
  const close = async () => {
    rmSync(join(root, 'hold-index'), { force: true })
    await stopProcess(apiProcess)
    proxy.closeAllConnections()
    await new Promise<void>((done) => proxy.close(() => done()))
    log.end()
  }
  try { await ready() } catch (error) { await close(); throw error }
  return {
    root, url, python, backend, source: join(root, 'source'), derived: join(root, 'derived'),
    async request<T>(method: string, path: string, body?: unknown): Promise<T> {
      const response = await fetch(`${url}/api/v1${path}`, {
        method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body),
      })
      if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`)
      return await response.json() as T
    },
    async crash() {
      const exited = once(apiProcess, 'exit')
      apiProcess.kill('SIGKILL')
      await exited
    },
    async restart() { apiProcess = launch(); await ready() },
    close,
  }
}
