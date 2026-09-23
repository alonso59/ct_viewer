import type { TFunction } from 'i18next'

import type { ItemRecord } from '../../api'

/** "Scan 01 · Full" / "Scan 01 · VOI L" (VW-11 order: phase, scan, scope, side) */
export function itemLabel(it: Pick<ItemRecord, 'scan_idx' | 'scope' | 'side'>, t: TFunction): string {
  const scope = it.scope === 'complete' ? t('item.full') : t('item.voiSide', { side: it.side })
  return t('item.label', { scan: it.scan_idx, scope })
}
