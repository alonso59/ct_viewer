// SRC-19: use the real shared inspection window before returning to adapter selection.
import { expect, type Page } from '@playwright/test'

export async function continueImportInspection(page: Page) {
  const inspection = page.getByRole('dialog', { name: 'Inspect import source', exact: true })
  await inspection.getByRole('button', { name: 'Continue import', exact: true }).click({ timeout: 30_000 })
  const wizard = page.getByRole('dialog', { name: 'Import data', exact: true })
  await expect(wizard).toBeVisible()
  return wizard
}

// Preview and indexing use the same durable background window as discovery.
export async function continueImportPreview(page: Page) {
  return continueImportInspection(page)
}

export async function finishImportIndex(page: Page) {
  const inspection = page.getByRole('dialog').filter({ has: page.getByRole('button', { name: 'Continue import', exact: true }) })
  await inspection.getByRole('button', { name: 'Continue import', exact: true }).click({ timeout: 30_000 })
}
