// UI-12 / UI-27 (AUD-A3-16): Settings in the real app: theme and interface size apply at once, the
// reviewer field is labelled, and recording a key that another command uses asks first.
import { expect, test } from '@playwright/test'

import { importedProject } from './helpers'

test('theme, size and a rebinding that asks before taking a key in use', async ({ page }) => {
  const pid = await importedProject(`Settings ${Date.now()}`)
  await page.goto(`/p/${pid}`)
  await expect(page.getByRole('tree', { name: 'Explorer' })).toBeVisible({ timeout: 30_000 })
  await page.keyboard.press('ControlOrMeta+,')
  const settings = page.getByRole('complementary', { name: 'Settings' })
  await settings.getByRole('group', { name: 'Theme' }).getByRole('button', { name: 'Light', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await settings.getByRole('group', { name: 'Interface size' }).getByRole('button', { name: 'Large', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-size', 'large')
  await expect(settings.getByLabel('Reviewer name', { exact: true })).toBeVisible()

  // Toggle panel ← the side bar's keys: asks first; Cancel keeps both as they were
  await settings.getByLabel('Keybindings').fill('Toggle panel')
  const panelKeys = settings.getByRole('button', { name: /^Toggle panel: / })
  const before = await panelKeys.innerText()
  await panelKeys.click()
  await page.keyboard.press('ControlOrMeta+b')
  const conflict = settings.getByRole('alert')
  await expect(conflict).toContainText('is already used by Toggle side bar')
  await conflict.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(conflict).toBeHidden()
  await expect(panelKeys).toHaveText(before)
  // Replace takes it: the panel's keys change, the side bar has none
  await panelKeys.click()
  await page.keyboard.press('ControlOrMeta+b')
  await settings.getByRole('alert').getByRole('button', { name: 'Replace', exact: true }).click()
  await expect(panelKeys).not.toHaveText(before)
  await settings.getByLabel('Keybindings').fill('Toggle side bar')
  await expect(settings.getByRole('button', { name: 'Toggle side bar: No keys' })).toBeVisible()
})
