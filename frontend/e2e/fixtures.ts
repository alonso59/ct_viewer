// PRJ-19 journeys use disposable datasets; the shared TST-07 fixtures stay immutable.
import { cpSync, existsSync, realpathSync } from 'node:fs'
import { isAbsolute, join, relative, sep } from 'node:path'

export function copyDataset(source: string, derived: string, name: string): string {
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) throw new Error('Invalid test dataset name')
  const target = join(realpathSync(derived), name)
  const path = relative(realpathSync(source), target)
  if (!path || (!path.startsWith(`..${sep}`) && path !== '..' && !isAbsolute(path))) throw new Error('Test output overlaps fixture sources')
  if (existsSync(target)) throw new Error('Test dataset already exists')
  const managed = new Set(['.workbench', 'derived', 'recycle_bin', '.gitignore'])
  cpSync(source, target, {
    recursive: true,
    filter: (file) => !relative(source, file).split(sep).some((part) => managed.has(part)),
  })
  return target
}
