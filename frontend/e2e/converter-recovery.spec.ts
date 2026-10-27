// TST-24/B04-B06/B08: real native cancellation/API death, fresh browser restore and one registration.
import { execFile, spawn } from 'node:child_process'
import { readFileSync, readdirSync, statSync, unlinkSync } from 'node:fs'
import { join } from 'node:path'
import { promisify } from 'node:util'

import { expect, test as base, type BrowserContext } from '@playwright/test'

import type { SourceOperation } from '../src/api/types'
import { startRecoveryServer } from './dicomRecovery'
import { stopProcess } from './processes'
import { fixtureHashes } from './tst07'

const execute = promisify(execFile)
const test = base.extend<{ server: Awaited<ReturnType<typeof startRecoveryServer>> }>({
  server: async ({ browserName }, provide, info) => {
    const server = await startRecoveryServer(info.outputPath(`native-${browserName}`))
    try { await provide(server) } finally { await server.close() }
  },
})
test.use({ actionTimeout: 15_000, navigationTimeout: 30_000 })

for (const scope of ['dataset', 'project']) {
  for (const action of ['cancel', 'crash']) {
    test(`${scope}: ${action} inside native Execute restores the same conversion`, async ({ page, browser, server }, info) => {
      test.setTimeout(180_000)
      const sentinel = spawn(server.python, ['-c', 'import sys;sys.stdin.buffer.read()'], { stdio: ['pipe', 'ignore', 'ignore'] })
      let recoveredContext: BrowserContext | undefined
      try {
        const inputs = fixtureHashes(server.source)
        let pid: string | undefined
        if (scope === 'project') {
          pid = (await server.request<{ project_id: string }>('POST', '/projects', { name: 'Native recovery', packs: [] })).project_id
          await server.request('PUT', `/projects/${pid}/roots/DERIVED`, { path: server.derived, role: 'derived' })
        }
        const operation = await server.request<{ operation_id: string }>('POST', '/source-operations', {
          path: server.source, project_id: pid, purpose: 'convert', prepare_plan: true,
          idempotency_key: 'browser-native-recovery', settings: { phase_analyzer: false, anonymize: 'none' },
        })
        const record = () => server.request<SourceOperation>('GET', `/source-operations/${operation.operation_id}`)
        await expect.poll(async () => (await record()).status, { timeout: 30_000 }).toBe('completed')
        await page.goto(server.url)
        await page.getByRole('button', { name: /Convert DICOM/ }).click()
        let dialog = page.getByRole('dialog', { name: 'Convert DICOM', exact: true })
        await dialog.getByRole('combobox', { name: 'Recent operations' }).selectOption(operation.operation_id)
        await dialog.getByRole('button', { name: /Convert 2 series/ }).click()
        const workspace = join(server.root, 'workspace')
        const barriers = () => readdirSync(workspace, { recursive: true, encoding: 'utf8' }).filter((p) => p.endsWith('native-writer-barrier.json'))
        await expect.poll(() => barriers().length, { timeout: 45_000 }).toBe(1)
        const barrier = JSON.parse(readFileSync(join(workspace, barriers()[0]!), 'utf8')) as { pid: number }
        const running = await record()
        const original = running.conversion_run!
        expect(original).toBeTruthy()
        const commits = Object.fromEntries(Object.entries(fixtureHashes(server.derived))
          .filter(([p]) => p.endsWith('.nii.gz') && !p.split('/').some((part) => part.startsWith('.')))
          .map(([p, sha]) => [p, { sha, mtime: String(statSync(join(server.derived, p), { bigint: true }).mtimeNs) }]))
        expect(Object.keys(commits)).toHaveLength(1)
        const second = await page.context().newPage()
        await second.goto(server.url)
        await expect(second.getByRole('combobox', { name: 'Recent operations' })).toHaveValue(operation.operation_id)
        expect((await server.request<{ items: unknown[] }>('GET', '/source-operations')).items).toHaveLength(1)
        await second.close()
        await page.keyboard.press('Escape')
        await expect(page.getByTestId('conv-chip')).toBeVisible()
        for (const theme of ['light', 'dark']) {
          await page.keyboard.press('Control+Shift+P')
          const palette = page.getByRole('dialog')
          await palette.getByRole('combobox').fill('Toggle light')
          await palette.getByRole('option', { name: /Toggle light \/ dark theme/ }).click()
          await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
        }
        await page.reload()
        await page.getByTestId('conv-chip').getByRole('button', { name: 'Show', exact: true }).click()
        if (action === 'cancel') {
          await dialog.getByRole('button', { name: 'Cancel conversion', exact: true }).click()
          await expect.poll(async () => {
            const value = await record()
            return value.status === 'cancelled' && value.cleanup_verified
          }, { timeout: 30_000 }).toBe(true)
        } else {
          await server.crash()
        }
        const owner = JSON.parse(readFileSync(join(workspace, barriers()[0]!.replace('native-writer-barrier.json', 'process.json')), 'utf8')) as { group: number; pid: number }
        expect(owner.pid).toBe(barrier.pid)
        await execute(server.python, ['-c', 'import sys,time;from app.tasks.dicom_process import group_running;end=time.monotonic()+5\nwhile group_running(int(sys.argv[1])) and time.monotonic()<end:time.sleep(.02)\nassert not group_running(int(sys.argv[1]))', String(owner.group)], { cwd: server.backend })
        unlinkSync(join(server.root, 'pause'))
        if (action === 'crash') await server.restart()
        await page.context().close()
        recoveredContext = await browser.newContext()
        page = await recoveredContext.newPage()
        await page.goto(server.url)
        await page.getByRole('button', { name: /Convert DICOM/ }).click()
        dialog = page.getByRole('dialog', { name: 'Convert DICOM', exact: true })
        await dialog.getByRole('combobox', { name: 'Recent operations' }).selectOption(operation.operation_id)
        if (action === 'crash') {
          await expect.poll(async () => (await record()).status).toBe('interrupted')
          await expect(dialog).toContainText('Interrupted')
        }
        await dialog.getByRole('button', { name: 'Resume pending work', exact: true }).click()
        await expect.poll(async () => (await record()).status, { timeout: 45_000 }).toBe('completed')
        const completed = await record()
        expect(completed.conversion_run!.run_id).toBe(original.run_id)
        expect(completed.conversion_run!.attempts).toBe(original.attempts + 1)
        if ('dataset_dir' in original) {
          expect(completed.conversion_run).toHaveProperty('dataset_dir', original.dataset_dir)
        } else {
          expect(completed.conversion_run).toHaveProperty('output_dir', original.output_dir)
        }
        expect(completed.cleanup_verified).toBe(true)
        const finalHashes = fixtureHashes(server.derived)
        const images = Object.keys(finalHashes).filter((p) => p.endsWith('.nii.gz') && !p.split('/').some((part) => part.startsWith('.')))
        expect(images).toHaveLength(2)
        expect(Object.keys(finalHashes).filter((p) => /\.tmp\.nii/.test(p))).toEqual([])
        await execute(server.python, ['-c', 'import sys,nibabel as n,numpy as np\nfor p in sys.argv[1:]:\n im=n.load(p);assert im.shape==(5,4,12);marker,=np.argwhere(im.get_fdata()==2000);np.testing.assert_allclose(im.affine@[*marker,1],[18.6,29.1,107.5,1],atol=1e-4)', ...images.map((p) => join(server.derived, p))], { cwd: server.backend })
        expect(fixtureHashes(server.source)).toEqual(inputs)
        for (const [p, saved] of Object.entries(commits)) {
          expect(finalHashes[p]).toBe(saved.sha)
          expect(String(statSync(join(server.derived, p), { bigint: true }).mtimeNs)).toBe(saved.mtime)
        }
        const runs = await server.request<unknown[]>('GET', pid ? `/projects/${pid}/task-runs` : '/task-runs')
        expect(runs).toHaveLength(1)
        if (pid) expect((await server.request<{ total: number }>('GET', `/projects/${pid}/imports`)).total).toBe(1)
        else expect(await server.request('GET', '/projects')).toEqual([])
        expect(sentinel.exitCode).toBeNull()
        expect(sentinel.signalCode).toBeNull()
        await info.attach('native-recovery.json', { body: JSON.stringify({ scope, action, run_id: original.run_id, completed: completed.status, source_unchanged: true, committed_images_unchanged: true, worker_group_gone: true, sentinel_alive: true }), contentType: 'application/json' })
      } finally {
        await recoveredContext?.close()
        sentinel.stdin.end()
        await stopProcess(sentinel)
      }
    })
  }
}
