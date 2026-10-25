// The scan's phase is set by the Phase control next to the switcher.
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useTranslation } from 'react-i18next'

import type { ItemRecord, Phase } from '../../api'
import { PhaseChip } from '../../lib'
import { Icon, codicon } from '../../theme'

interface ScanInfo {
  idx: string
  phase: Phase
  modality: string | null
  description: string
  slices: number | null
}

/** One entry per scan of the case, in scan order; its facts come from the full-volume item */
export function scansOf(items: ItemRecord[]): ScanInfo[] {
  const by = new Map<string, ItemRecord[]>()
  for (const i of items) by.set(i.scan_idx, [...(by.get(i.scan_idx) ?? []), i])
  return [...by.entries()]
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
    .map(([idx, its]) => {
      const full = its.find((i) => i.scope === 'complete') ?? its[0]!
      const d = full.extra?.series_description
      return {
        idx,
        phase: full.phase.canonical as Phase,
        modality: full.modality ?? null,
        description: typeof d === 'string' ? d : '',
        slices: full.geometry?.shape[2] ?? null,
      }
    })
}

export function ItemSwitcher({ items, current, onPick }: { items: ItemRecord[]; current: ItemRecord; onPick: (id: string) => void }) {
  const { t } = useTranslation()
  const scans = scansOf(items)
  const at = scans.findIndex((s) => s.idx === current.scan_idx)
  const inScan = items.filter((i) => i.scan_idx === current.scan_idx)
  const hasVoi = inScan.some((i) => i.scope === 'voi')
  const sides = inScan.filter((i) => i.scope === 'voi').map((i) => i.side)
  const pick = (f: (i: ItemRecord) => boolean) => {
    const target = items.find((i) => f(i) && i.scope === current.scope && i.side === current.side) ?? items.find(f)
    if (target) onPick(target.item_id)
  }
  const goScan = (idx: string) => pick((i) => i.scan_idx === idx)
  const step = (d: number) => {
    const s = scans[at + d]
    if (s) goScan(s.idx)
  }
  const inCurrentScan = (scope: ItemRecord['scope']) => (i: ItemRecord) => i.scan_idx === current.scan_idx && i.scope === scope
  return (
    <div className="switcher" role="toolbar" aria-label={t('viewer.itemSwitcher')}>
      <span className="switcher-label">{t('viewer.scan')}</span>
      <button type="button" className="icon-btn" aria-label={t('viewer.scanPrev')} title={t('viewer.scanPrev')} disabled={at <= 0} onClick={() => step(-1)}>
        <Icon spec={codicon('chevron-left')} />
      </button>
      <Menu.Root>
        <Menu.Trigger className="scan-select" aria-label={t('viewer.scanIndex', { scan: current.scan_idx })} title={t('viewer.scanPick')}>
          <span className="mono">{current.scan_idx}</span>
          <PhaseChip phase={current.phase.canonical as Phase} />
          {scans.length > 1 ? <span className="muted">{t('viewer.scanPosition', { n: at + 1, total: scans.length })}</span> : null}
          <Icon spec={codicon('chevron-down')} />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="overlay menu scan-menu" sideOffset={4} align="start">
            {scans.map((s) => (
              <Menu.Item key={s.idx} className="menu-item" aria-label={t('viewer.scanIndex', { scan: s.idx })} onSelect={() => goScan(s.idx)}>
                <Icon spec={codicon(s.idx === current.scan_idx ? 'check' : 'blank')} />
                <span className="mono">{s.idx}</span>
                <PhaseChip phase={s.phase} />
                <span className="scan-meta">
                  {[s.modality, s.slices != null ? t('viewer.scanSlices', { n: s.slices }) : null, s.description].filter(Boolean).join(' · ')}
                </span>
              </Menu.Item>
            ))}
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      <button type="button" className="icon-btn" aria-label={t('viewer.scanNext')} title={t('viewer.scanNext')} disabled={at < 0 || at + 1 >= scans.length} onClick={() => step(1)}>
        <Icon spec={codicon('chevron-right')} />
      </button>
      <span className="switcher-sep" />
      <span className="switcher-label">{t('viewer.scope')}</span>
      <div className="seg" role="group" aria-label={t('viewer.scope')}>
        <button type="button" data-scope="complete" aria-pressed={current.scope === 'complete'} title={t('viewer.scopeFullHelp')} onClick={() => pick(inCurrentScan('complete'))}>
          {t('item.full')}
        </button>
        <button type="button" data-scope="voi" aria-pressed={current.scope === 'voi'} disabled={!hasVoi} title={hasVoi ? t('viewer.scopeVoiHelp') : t('viewer.scopeNoVoi')} onClick={() => pick(inCurrentScan('voi'))}>
          {t('item.voi')}
        </button>
      </div>
      {current.scope === 'voi' ? (
        <div className="seg" role="group" aria-label={t('viewer.side')}>
          {sides.map((s) => (
            <button key={s} type="button" aria-pressed={current.side === s} onClick={() => pick((i) => inCurrentScan('voi')(i) && i.side === s)}>
              {s}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
