// Item display names (UI-08, AUD-A1-13): people read "case_00055 · NP · Full", not the internal
// `item_id` "case_00055.01.complete.-". The raw id stays in the tooltip and in every copy action.
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'

import { keys, queryClient, type CaseDetail, type ItemRecord } from '../api'

export interface ItemParts {
  case_id: string
  scan_idx: string
  scope: string
  side: string
}

/** DATA_MODEL §item_id: `{case_id}.{scan_idx}.{scope}.{side}`; a case id may itself hold dots */
export function parseItemId(id: string): ItemParts | null {
  const parts = id.split('.')
  if (parts.length < 4) return null
  const [scan_idx = '', scope = '', side = ''] = parts.slice(-3)
  if (scope !== 'complete' && scope !== 'voi') return null
  return { case_id: parts.slice(0, -3).join('.'), scan_idx, scope, side }
}

/** The phase of an item when a loaded case or item already knows it (no request) */
export function knownPhase(pid: string, id: string): string | null {
  const it = queryClient.getQueryData<ItemRecord>(keys.item(pid, id))
  if (it) return it.phase.canonical
  const p = parseItemId(id)
  const c = p ? queryClient.getQueryData<CaseDetail>(keys.case(pid, p.case_id)) : undefined
  return c?.items.find((i) => i.item_id === id)?.phase.canonical ?? null
}

/** "case · phase · scope · side": the phase when known, else the scan number ("Scan 01") */
export function itemName(id: string, t: TFunction, phase?: string | null): string {
  const p = parseItemId(id)
  if (!p) return id
  const scope = p.scope === 'complete' ? t('item.full') : t('item.voiSide', { side: p.side })
  return t('item.name', { case: p.case_id, part: phase ?? t('item.scanShort', { scan: p.scan_idx }), scope })
}

/** An item's name in one truncated line; the raw id in the tooltip (copy keeps using the id) */
export function ItemName({ id, phase, pid, className }: { id: string; phase?: string | null; pid?: string; className?: string }) {
  const { t } = useTranslation()
  const ph = phase ?? (pid ? knownPhase(pid, id) : null)
  return (
    <span className={`truncate ${className ?? ''}`} title={id}>
      {itemName(id, t, ph)}
    </span>
  )
}
