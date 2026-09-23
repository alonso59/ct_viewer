// CUR-08 rollup: the most severe status wins
import { STATUS_SEVERITY, type CurationStatus } from './types'

export function rollup(statuses: CurationStatus[]): CurationStatus {
  return statuses.reduce<CurationStatus>(
    (worst, s) => (STATUS_SEVERITY[s] > STATUS_SEVERITY[worst] ? s : worst),
    'not_reviewed',
  )
}
