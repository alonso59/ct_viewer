// @vitest-environment jsdom
// VW-11 / AUD-A1-12 on the recorded API (TST-04): the case header picks a scan from a drop-down
// (not a row of chips), with previous / next, and keeps the Full / VOI choice when it moves.
import { fireEvent, render, screen, within } from '@testing-library/react'

import '../../i18n'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { ItemSwitcher, scansOf } from './ItemSwitcher'

const caseItems = async () => (await api.getCase(DEMO_PID, 'case_00002')).items.filter((i) => i.status !== 'excluded_upstream')

test('one entry per scan, in scan order, with its phase', async () => {
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
  // one trigger names the current scan
  expect(screen.queryAllByRole('button', { name: /^Scan \d+$/ })).toHaveLength(1)
  const trigger = screen.getByRole('button', { name: `Scan ${current.scan_idx}` })
  expect(trigger).toHaveTextContent(`1 of ${scans.length}`)
  expect(screen.getByRole('button', { name: 'Previous scan' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Next scan' }))
  expect(onPick).toHaveBeenLastCalledWith(items.find((i) => i.scan_idx === scans[1]!.idx && i.scope === 'complete')!.item_id)
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })
  const menu = await screen.findByRole('menu')
  expect(within(menu).getAllByRole('menuitem')).toHaveLength(scans.length)
  fireEvent.click(within(menu).getByRole('menuitem', { name: `Scan ${scans[1]!.idx}` }))
  expect(onPick).toHaveBeenCalledTimes(2)
})
