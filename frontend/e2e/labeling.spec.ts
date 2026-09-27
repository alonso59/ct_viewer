// TST-19 (LBL-03..06): two reviewers label the same table; edits appear live in the other browser,
// columns become `lbl.*` variables, the case's Inspector section edits its row (AUD-A1-05), the
// Labels view saves a typed name whole (AUD-A5-07), and a view-only link shows the table read-only.

import { expect, test, type Browser, type Page } from '@playwright/test'

import { api, importedProject } from './helpers'

async function reviewer(browser: Browser, name: string, url: string): Promise<Page> {
  const ctx = await browser.newContext()
  await ctx.addInitScript((n) => localStorage.setItem('rw.reviewer', JSON.stringify({ state: { name: n }, version: 0 })), name)
  const page = await ctx.newPage()
  await page.goto(url)
  await expect(page.getByRole('contentinfo', { name: 'Status bar' }).getByText('live', { exact: true }).first()).toBeVisible({ timeout: 30_000 })
  return page
}

const cell = (page: Page, row: number, col: number) => page.getByRole('row').filter({ has: page.getByRole('rowheader') }).nth(row).getByRole('gridcell').nth(col)

test('two reviewers label a patient table live; columns become variables', async ({ browser }) => {
  test.setTimeout(120_000)
  const pid = await importedProject(`Labeling ${Date.now()}`)
  const t = await api<{ table_id: string }>('POST', `/plugins/labeling/projects/${pid}/tables`, {
    name: 'Review', level: 'case', columns: [{ name: 'Grade', type: 'category', levels: ['G1', 'G2', 'G3'] }, { name: 'Tumour', type: 'bool' }],
  })
  const url = `/p/${pid}/labeling/${t.table_id}`
  const a = await reviewer(browser, 'Dr. A', url)
  const b = await reviewer(browser, 'Dr. B', url)

  // A sets a category with the keyboard editor; B sees it without reloading (LBL-05)
  await cell(a, 0, 0).click()
  await a.keyboard.press('Enter')
  await a.getByRole('combobox', { name: 'Grade' }).selectOption('G2')
  await expect(cell(a, 0, 0)).toHaveText('G2')
  await expect(cell(b, 0, 0)).toHaveText('G2', { timeout: 15_000 })
  // B toggles a yes/no cell with Space; A sees it
  await cell(b, 1, 1).click()
  await b.keyboard.press(' ')
  await expect(cell(a, 1, 1)).toHaveText('✓', { timeout: 15_000 })
  // History of the cell shows the reviewer (LBL-04)
  await cell(a, 1, 1).click()
  await expect(a.getByRole('complementary', { name: 'Cell history' })).toContainText('Dr. B')

  // LBL-06: the column is a typed variable
  await expect.poll(async () => (await api<{ variables: { name: string; type: string }[] }>('GET', `/projects/${pid}/variables`)).variables.find((v) => v.name === 'lbl.review.grade')?.type, { timeout: 15_000 }).toBe('categorical')

  // AUD-A1-05: from the case, the Inspector section fills the case's row of every table; B's table
  // tab shows the edit live
  const target = ((await b.getByRole('rowheader').first().textContent()) ?? '').trim()
  await a.goto(`/p/${pid}/case/${target}`)
  // ADR-0028: the inspector is in the title bar's Layout menu
  await a.getByRole('banner').getByRole('button', { name: /^Layout/ }).click()
  await a.getByRole('menuitemcheckbox', { name: /Inspector/ }).click()
  const section = a.locator('.inspector').getByRole('group', { name: 'Review' })
  await section.getByRole('button', { name: 'Edit Grade' }).click()
  await section.getByRole('combobox', { name: 'Grade' }).selectOption('G3')
  await expect(section.getByRole('button', { name: 'Edit Grade' })).toHaveText('G3')
  await expect(cell(b, 0, 0)).toHaveText('G3', { timeout: 15_000 })

  // AUD-A5-07 (PRJ-07): a label name typed at full speed is saved whole, once, on blur
  await a.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name: 'Labels' }).click()
  const name = a.getByRole('complementary', { name: 'Labels' }).getByRole('textbox', { name: 'Label name' }).first()
  const before = await name.inputValue()
  const patches: number[] = []
  a.on('response', (r) => {
    if (r.request().method() === 'PATCH' && r.url().endsWith(`/projects/${pid}`)) patches.push(r.status())
  })
  await name.click()
  await name.press('End')
  await a.keyboard.type('abcdefghij', { delay: 0 })
  await name.press('Tab')
  await expect.poll(async () => (await api<{ label_map: { name: string }[] }>('GET', `/projects/${pid}`)).label_map[0]?.name).toBe(`${before}abcdefghij`)
  await expect.poll(() => patches).toEqual([200])

  // A view-only link shows the table, read-only
  const { view_token } = await api<{ view_token: string }>('POST', `/projects/${pid}/view-token`)
  const v = await a.context().newPage()
  await v.goto(`/v/${view_token}`)
  await v.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name: 'Labeling' }).click()
  await v.getByRole('complementary', { name: 'Labeling' }).getByRole('button', { name: /^Review/ }).click()
  await expect(v.getByText('Read only', { exact: true })).toBeVisible()
  await expect(cell(v, 0, 0)).toHaveText('G3')
  await cell(v, 2, 1).click()
  await v.keyboard.press(' ')
  await expect(cell(v, 2, 1)).toHaveText('')
  await a.context().close()
  await b.context().close()
})
