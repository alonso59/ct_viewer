// @vitest-environment jsdom
// VW-11 / AUD-A1-12 on the recorded API (TST-04): the case header picks a scan from a drop-down
// (not a row of chips), with previous / next, and keeps the Full / VOI choice when it moves.
import { fireEvent, render, screen, within } from '@testing-library/react'

import '../../i18n'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { ItemSwitcher, scansOf } from './ItemSwitcher'

const caseItems = async () => (await api.getCase(DEMO_PID, 'case_00002')).items.filter((i) => i.status !== 'excluded_upstream')

test('one entry per scan (each its own exam here, so in scan order), with its phase', async () => {
  const items = await caseItems()
  const scans = scansOf(items)
  expect(scans.map((s) => s.idx)).toEqual([...new Set(items.map((i) => i.scan_idx))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true })))
  for (const s of scans) expect(s.phase).toBe(items.find((i) => i.scan_idx === s.idx && i.scope === 'complete')!.phase.canonical)
})

test('the scan drop-down lists the scans and picks one; previous / next step through them', async () => {
  const items = await caseItems()
  const scans = scansOf(items)
  expect(scans.length).toBeGreaterThan(1)
  const current = items.find((i) => i.scan_idx === scans[0]!.idx && i.scope === 'complete')!
  const onPick = vi.fn()
  render(<ItemSwitcher items={items} current={current} onPick={onPick} />)
  // one trigger names the current scan, with what it shows (phase, position)
  expect(screen.queryAllByRole('button', { name: /^Scan \d+ / })).toHaveLength(1)
  const trigger = screen.getByRole('button', { name: `Scan ${current.scan_idx} ${current.phase.canonical} 1 of ${scans.length}` })
  expect(trigger).toHaveTextContent(`1 of ${scans.length}`)
  expect(screen.getByRole('button', { name: 'Previous scan' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Next scan' }))
  expect(onPick).toHaveBeenLastCalledWith(items.find((i) => i.scan_idx === scans[1]!.idx && i.scope === 'complete')!.item_id)
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })
  const menu = await screen.findByRole('menu')
  expect(within(menu).getAllByRole('menuitem')).toHaveLength(scans.length)
  fireEvent.click(within(menu).getByRole('menuitem', { name: new RegExp(`^Scan ${scans[1]!.idx} ${scans[1]!.phase}`) }))
  expect(onPick).toHaveBeenCalledTimes(2)
})

test('a scan shows its modality, with the MR component when it is not magnitude (VW-11)', async () => {
  const items = await caseItems()
  const [first, ...rest] = items
  const mr = { ...first!, modality: 'MR', image_component: 'PHASE' }
  expect(scansOf([mr, ...rest]).find((s) => s.idx === mr.scan_idx)).toMatchObject({ modality: 'MR', component: 'PHASE' })
  expect(scansOf([{ ...mr, image_component: 'MAGNITUDE' }])[0]!.component).toBeNull()
  render(<ItemSwitcher items={[mr, ...rest]} current={mr} onPick={() => {}} />)
  fireEvent.pointerDown(screen.getByRole('button', { name: new RegExp(`^Scan ${mr.scan_idx} `) }), { button: 0, ctrlKey: false })
  expect(await screen.findByText(/^MR · Phase/)).toBeInTheDocument()
})

test('ADR-0057: scans by exam, series and part; previous / next follow that order and the menu has headings', async () => {
  const base = (await caseItems()).find((i) => i.scope === 'complete')!
  const mk = (idx: string, extra: Record<string, unknown>) => ({ ...base, item_id: `case_00002.${idx}.complete.-`, scan_idx: idx, extra })
  const ex = { study_uid: 'S1', days_from_first_scan: '0' }
  const items = [
    mk('205', { ...ex, series_uid: 'D#t4', series_number: '7' }),
    mk('155', { ...ex, series_uid: 'D', series_number: '7', series_description: 'dyn' }),
    mk('203', { ...ex, series_uid: 'D#t2', series_number: '7' }),
    mk('301', { study_uid: 'S2', days_from_first_scan: '84', series_uid: 'T', series_description: 'T2 ax' }),
  ]
  expect(scansOf(items).map((s) => [s.idx, s.part, s.description])).toEqual([['155', null, ''], ['203', 't2', ''], ['205', 't4', ''], ['301', null, 'T2 ax']])
  const onPick = vi.fn()
  render(<ItemSwitcher items={items} current={items[1]!} onPick={onPick} />)
  fireEvent.click(screen.getByRole('button', { name: 'Next scan' }))
  expect(onPick).toHaveBeenLastCalledWith('case_00002.203.complete.-')
  fireEvent.pointerDown(screen.getByRole('button', { name: /^Scan 155 / }), { button: 0, ctrlKey: false })
  const menu = await screen.findByRole('menu')
  expect(within(menu).getAllByRole('menuitem')).toHaveLength(4)
  for (const h of ['Exam · day 0', 'Series 7 · dyn', 'Exam · day 84']) expect(within(menu).getByText(h)).toBeInTheDocument()
  expect(within(menu).getByRole('menuitem', { name: /^Scan 205 .* t4 · / })).toBeInTheDocument()
})
