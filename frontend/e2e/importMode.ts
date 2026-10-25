// SRC-19: use the real shared inspection window before returning to adapter selection.
import { expect, type Page } from '@playwright/test'

export async function continueImportInspection(page: Page) {
  const inspection = page.getByRole('dialog', { name: 'Inspect import source', exact: true })
  await inspection.getByRole('button', { name: 'Continue import', exact: true }).click({ timeout: 30_000 })
  const wizard = page.getByRole('dialog', { name: 'Import data', exact: true })
  await expect(wizard).toBeVisible()
  return wizard
}
