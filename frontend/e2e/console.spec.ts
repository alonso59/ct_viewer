// CTF-19 / TST-26: the CTFlow console panel runs lines on the real server — help from the catalog,
// the project's cases, a refusal with its cause — and keeps one session between lines.
import { expect, test } from '@playwright/test'

import { importedProject } from './helpers'

test('the console runs commands in one session and shows refusals', async ({ page }) => {
  test.setTimeout(120_000)
  const pid = await importedProject(`Console ${Date.now()}`)
  // a line that is not a plain read is stamped with the reviewer name, as other writes are
  await page.addInitScript(() => localStorage.setItem('rw.reviewer', JSON.stringify({ state: { name: 'E2E' }, version: 0 })))
  await page.goto(`/p/${pid}`)
  await expect(page.getByRole('tree', { name: 'Explorer' })).toBeVisible({ timeout: 30_000 })
  const tab = page.getByRole('tab', { name: 'Console', exact: true })
  if (!(await tab.isVisible())) await page.keyboard.press('ControlOrMeta+j')
  await tab.click()
  const line = page.getByLabel('ctflow', { exact: true })
  const log = page.getByRole('log', { name: 'Console output' })

  await line.fill('help')
  await line.press('Enter')
  await expect(log).toContainText('cases [-phase P]')

  await line.fill('set n [llength [cases]]; puts "cases: $n"')
  await line.press('Enter')
  await expect(log).toContainText(/cases: [1-9]\d*/)
  await line.fill('puts again-$n') // the variable lives in the server session
  await line.press('Enter')
  await expect(log).toContainText(/again-[1-9]\d*/)

  await line.fill('status 01NOTARUN')
  await line.press('Enter')
  await expect(log).toContainText(/not found/i)

  await line.fill('ca')
  await line.press('Tab') // two matches: both are listed
  await expect(log).toContainText('cancel  cases')
  await line.fill('stat')
  await line.press('Tab')
  await expect(line).toHaveValue('status ')
})
