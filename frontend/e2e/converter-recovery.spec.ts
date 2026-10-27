// TST-24/B01-B06/B08: real import/result journeys, native cancellation/API death and restore.
import { execFile, spawn } from 'node:child_process'
import { readFileSync, readdirSync, statSync, unlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { promisify } from 'node:util'

import { expect, test as base, type BrowserContext } from '@playwright/test'

import type { SourceOperation } from '../src/api/types'
import { startRecoveryServer } from './dicomRecovery'
import { continueImportInspection, continueImportPreview, finishImportIndex } from './importMode'
import { openViaHistoryState } from './openMode'
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

test('project import discovers deep extensionless DICOM and converts after minimize/navigation', async ({ page, server }) => {
  test.setTimeout(180_000)
  unlinkSync(join(server.root, 'pause'))
  await execute(server.python, ['-c', `
import sys
from pathlib import Path
root = Path(sys.argv[1])
deep = root / "one/two/three/four"
deep.mkdir(parents=True)
(root / "P0").rename(deep / "P0")
for index, path in enumerate(sorted(root.rglob("*.dcm"))):
    path.rename(path.with_suffix("" if index % 2 else ".IMA"))
`, server.source])
  const inputs = fixtureHashes(server.source)
  const { project_id: pid } = await server.request<{ project_id: string }>('POST', '/projects', { name: 'Deep DICOM import', packs: [] })
  await server.request('PUT', `/projects/${pid}/roots/DERIVED`, { path: server.derived, role: 'derived' })
  await page.goto(`${server.url}/p/${pid}`)
  await page.keyboard.press('ControlOrMeta+Shift+P')
  await page.getByRole('dialog').getByRole('combobox').fill('Import data')
  await page.getByRole('option', { name: /Import data/ }).click()
  let wizard = page.getByRole('dialog', { name: 'Import data', exact: true })
  await wizard.getByRole('listbox', { name: 'Folders' }).getByRole('button', { name: server.source, exact: true }).click()
  await wizard.getByRole('button', { name: 'Next', exact: true }).click()
  wizard = await continueImportInspection(page)
  await wizard.getByRole('radio', { name: /DICOM/ }).check()
  const created = page.waitForResponse((r) => r.url().endsWith('/source-operations') && r.request().method() === 'POST')
  await wizard.getByRole('button', { name: 'Next', exact: true }).click()
  const { operation_id: oid } = await (await created).json() as { operation_id: string }
  const dialog = page.getByRole('dialog', { name: 'Convert DICOM', exact: true })
  await expect(dialog.getByRole('button', { name: /Convert 2 series/ })).toBeVisible({ timeout: 30_000 })
  await dialog.getByRole('button', { name: 'Minimize', exact: true }).click()
  await page.getByRole('navigation', { name: /Activity bar/ }).getByRole('button', { name: 'Variables', exact: true }).click()
  await page.getByTestId('conv-chip').getByRole('button', { name: 'Show', exact: true }).click()
  await dialog.getByRole('button', { name: /Convert 2 series/ }).click()
  await dialog.getByRole('button', { name: 'Show the result' }).click({ timeout: 60_000 })
  await expect.poll(async () => (await server.request<SourceOperation>('GET', `/source-operations/${oid}`)).status).toBe('completed')
  expect((await server.request<{ total: number }>('GET', `/projects/${pid}/items?limit=1`)).total).toBe(2)
  const imports = await server.request<{ items: unknown[] }>('GET', `/projects/${pid}/imports`)
  expect(imports.items).toHaveLength(1)
  expect(fixtureHashes(server.source)).toEqual(inputs)
})

test('later-page DICOM series retains all 750 slices in a root with more than 500 series', async ({ page, server }) => {
  test.setTimeout(180_000)
  unlinkSync(join(server.root, 'pause'))
  const fixture = await execute(server.python, ['-c', `
import json, sys
from pathlib import Path
import SimpleITK as sitk
from tools.dicom_fixtures import write_series
root = Path(sys.argv[1])
for index in range(500):
    write_series(root / f"AA{index:04}", patient_id=f"S{index:04}",
                 description=f"Small-{index:04}", shape=(5, 4, 3), marker=(2, 1, 2), seed=f"large-browser-{index}")
long = root / "ZZZ"
info = write_series(long, patient_id="Long", description="Long-750", shape=(5, 4, 750),
                    marker=(2, 1, 749), seed="large-browser-long")
files = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(long), info["series_uid"])
print(json.dumps([str(Path(path).relative_to(root)) for path in files]))
`, server.source], { cwd: server.backend })
  const expectedFiles = JSON.parse(fixture.stdout) as string[]
  expect(expectedFiles).toHaveLength(750)
  const inputs = fixtureHashes(server.source)
  await page.goto(server.url)
  await openViaHistoryState(page, server.source)
  await expect(page).toHaveURL(/\/open\/[0-9A-Z]{26}$/, { timeout: 60_000 })
  const sid = page.url().split('/').at(-1)!
  const files = page.getByRole('listbox', { name: 'Files' })
  await expect(files.getByRole('button')).toHaveCount(50)
  for (let index = 1; index <= 10; index++) {
    await page.getByRole('button', { name: 'Next page', exact: true }).click()
    if (index < 10) await expect(files.getByRole('button').first()).toHaveText(`Small-${String(index * 50).padStart(4, '0')}`)
    else await expect(files.getByRole('button', { name: 'Long-750', exact: true })).toBeVisible()
  }
  await files.getByRole('button', { name: 'Long-750', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Axial', exact: true }).getByRole('slider')).toHaveAttribute('max', '750', { timeout: 30_000 })
  const first = await server.request<{ items: { n: number }[]; next_cursor: string; total: number }>('GET', `/open/${sid}/items?limit=500`)
  const last = await server.request<{ items: { n: number; name: string; n_slices: number; files: string[] }[]; next_cursor: string | null }>('GET', `/open/${sid}/items?limit=500&cursor=${first.next_cursor}`)
  expect(first.total).toBe(503)
  expect(last.next_cursor).toBeNull()
  expect(new Set([...first.items, ...last.items].map((item) => item.n)).size).toBe(503)
  const long = last.items.find((item) => item.name === 'Long-750')!
  expect(long.n_slices).toBe(750)
  expect(long.files).toEqual(expectedFiles)
  const image = await page.request.get(`${server.url}/api/v1/open/${sid}/items/${long.n}/image`)
  expect(image.ok()).toBe(true)
  const output = join(server.derived, 'long-reference.nii.gz')
  writeFileSync(output, await image.body())
  await execute(server.python, ['-c', `
import sys, nibabel as nib, numpy as np
image = nib.load(sys.argv[1]); pixels = np.asanyarray(image.dataobj)
assert pixels.shape == (5, 4, 750)
[marker] = np.argwhere(pixels == 2000)
assert np.count_nonzero(pixels == -100) == pixels.size - 1
np.testing.assert_allclose(image.affine @ [*marker, 1], [18.6, 29.1, 1972.5, 1], atol=1e-5)
`, output])
  await page.getByRole('button', { name: 'Convert DICOM…', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Convert DICOM', exact: true })
  await dialog.getByRole('button', { name: 'Dry run', exact: true }).click()
  await expect(dialog.getByRole('button', { name: /Convert 3 series/ })).toBeVisible({ timeout: 30_000 })
  await expect(dialog.getByText('503 series · 500 skipped', { exact: true })).toBeVisible()
  expect(fixtureHashes(server.source)).toEqual(inputs)
})

for (const destination of ['open', 'existing project']) {
  test(`workspace conversion result opens in ${destination}`, async ({ page, server }) => {
    test.setTimeout(180_000)
    unlinkSync(join(server.root, 'pause'))
    const inputs = fixtureHashes(server.source)
    const { project_id: pid } = await server.request<{ project_id: string }>('POST', '/projects', { name: 'Existing destination', packs: [] })
    const { operation_id: oid } = await server.request<{ operation_id: string }>('POST', '/source-operations', {
      path: server.source, purpose: 'convert', prepare_plan: true, idempotency_key: 'result-branch', settings: { phase_analyzer: false },
    })
    await expect.poll(async () => (await server.request<SourceOperation>('GET', `/source-operations/${oid}`)).status, { timeout: 30_000 }).toBe('completed')
    await page.goto(server.url)
    await page.getByRole('button', { name: /Convert DICOM/ }).click()
    const dialog = page.getByRole('dialog', { name: 'Convert DICOM', exact: true })
    await dialog.getByRole('combobox', { name: 'Recent operations' }).selectOption(oid)
    await dialog.getByRole('button', { name: /Convert 2 series/ }).click()
    await dialog.getByRole('button', { name: 'Show the result' }).click({ timeout: 60_000 })
    if (destination === 'open') {
      await dialog.getByRole('button', { name: 'Open', exact: true }).click()
      await expect(page).toHaveURL(/\/open\/[0-9A-Z]{26}$/)
      await expect(page.locator('.vp').first()).toBeVisible()
      await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
    } else {
      await dialog.getByRole('combobox', { name: 'Add to project', exact: true }).selectOption(pid)
      await dialog.getByRole('button', { name: 'Add to project', exact: true }).click()
      const wizard = await continueImportInspection(page)
      await wizard.getByRole('button', { name: 'Next', exact: true }).click()
      await continueImportPreview(page)
      await wizard.getByRole('button', { name: 'Import and index', exact: true }).click()
      await finishImportIndex(page)
      expect((await server.request<{ total: number }>('GET', `/projects/${pid}/items?limit=1`)).total).toBe(2)
    }
    expect((await server.request<unknown[]>('GET', '/projects'))).toHaveLength(1)
    expect(fixtureHashes(server.source)).toEqual(inputs)
  })
}

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
