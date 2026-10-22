// PRJ-19 browser fixtures: GUI-managed projects must never write into the shared sources.
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { copyDataset } from '../../e2e/fixtures'

let root: string
beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'rw-copy-test-'))
  mkdirSync(join(root, 'source/nifti'), { recursive: true })
  writeFileSync(join(root, 'source/nifti/image.nii'), 'original')
  mkdirSync(join(root, 'derived'))
})
afterEach(() => rmSync(root, { recursive: true, force: true }))

test('GUI dataset copies are independent and leave prior app state behind', () => {
  mkdirSync(join(root, 'source/nifti/.workbench'), { recursive: true })
  writeFileSync(join(root, 'source/nifti/.workbench/state'), 'old state')
  const dataset = copyDataset(join(root, 'source'), join(root, 'derived'), 'gui')
  expect(readFileSync(join(dataset, 'nifti/image.nii'), 'utf8')).toBe('original')
  expect(existsSync(join(dataset, 'nifti/.workbench'))).toBe(false)
  writeFileSync(join(dataset, 'nifti/image.nii'), 'changed copy')
  expect(readFileSync(join(root, 'source/nifti/image.nii'), 'utf8')).toBe('original')
})

test('refuses an output inside the sources and never overwrites a prior copy', () => {
  const source = join(root, 'source')
  expect(() => copyDataset(source, source, 'gui')).toThrow()
  copyDataset(source, join(root, 'derived'), 'gui')
  expect(() => copyDataset(source, join(root, 'derived'), 'gui')).toThrow()
  expect(() => copyDataset(source, join(root, 'derived'), '../source')).toThrow()
})
