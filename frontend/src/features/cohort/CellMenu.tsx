import * as Menu from '@radix-ui/react-dropdown-menu'
import { useTranslation } from 'react-i18next'
import { create } from 'zustand'

import { ReviewerCancelled, useAppendEvent, useCurationState, useProject } from '../../api'
import { openItem } from '../explorer'
import { registry, toast, toastProblem, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { allRows } from './allRows'
import { pastedColumn, rowsOf, targetOf, useCellWriter, useClinicalColumns } from './clinical'
import { useCohort } from './store'

/** A right-clicked cell: its row (a scan's own item, or the case's first scan), column and value */
export interface CellTarget {
  caseId: string
  /** The scan row the cell is on; null on a case row */
  scanIdx: string | null
  itemId: string | null
  /** Variable column, when the cell is one */
  column: string | null
  value: string | number | null
  label: string
  x: number
  y: number
}

interface CellMenuState {
  target: CellTarget | null
  open: (target: CellTarget) => void
  close: () => void
}

export const useCellMenu = create<CellMenuState>()((set) => ({
  target: null,
  open: (target) => set({ target }),
  close: () => set({ target: null }),
}))

/** The floating menu of a grid cell: copy, filter by value, open in viewer, correction queue */
export function CellMenu() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const target = useCellMenu((s) => s.target)
  const close = useCellMenu((s) => s.close)
  const addVarValue = useCohort((s) => s.addVarValue)
  const setCompare = useCohort((s) => s.setCompare)
  const setSummary = useCohort((s) => s.setSummary)
  const setTags = useCohort((s) => s.setTags)
  const setTimeline = useCohort((s) => s.setTimeline)
  const setEditing = useCohort((s) => s.setEditing)
  const filters = useCohort((s) => s.filters)
  const sort = useCohort((s) => s.sort)
  const clinical = useClinicalColumns(pid)
  const write = useCellWriter(pid)
  const state = useCurationState(pid).data
  const defaultSeg = useProject(pid).data?.default_seg ?? 'imported'
  const append = useAppendEvent(pid)
  if (!target) return null
  const info = target.column ? clinical.get(target.column) : undefined
  const editable = info && !registry.readOnly && targetOf(info, target.caseId, target.scanIdx) !== null ? info : null
  // Bulk edits cover the filtered rows in the grid's order: fill one value, or paste a column
  // of values from the clipboard starting at this row
  const bulk = async (values: (rowValue: unknown, index: number, start: number) => unknown | undefined) => {
    if (!editable || !target.column) return
    try {
      const rows = rowsOf(editable, target.column, await allRows(pid, [target.column], filters, sort))
      const start = Math.max(0, rows.findIndex((r) => r.caseId === target.caseId && r.scanIdx === target.scanIdx))
      const cells = rows.flatMap((r, i) => {
        const value = values(r.value, i, start)
        return value === undefined ? [] : [{ r, cell: { column_id: editable.col.column_id, target: r.target, value: value === '' ? null : value } }]
      })
      await write(editable.table.table_id, cells.map((c) => c.cell), cells.map((c) => ({ ...c.cell, value: c.r.value ?? null })))
    } catch (e) {
      toastProblem(e)
    }
  }
  const fill = () => void bulk(() => (hasValue ? target.value : null))
  const paste = () =>
    void navigator.clipboard.readText().then((text) => {
      const lines = pastedColumn(text)
      return bulk((_, i, start) => (i >= start && i - start < lines.length ? lines[i - start] : undefined))
    }, () => toast({ message: t('cohort.edit.noClipboard'), tone: 'error' }))
  const hasValue = target.value !== null && target.value !== undefined && String(target.value) !== ''
  const copy = () => {
    const text = String(target.value)
    const done = () => toast({ message: t('cohort.menu.copied', { value: text }), tone: 'ok' })
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => toast({ message: text }))
    else toast({ message: text })
  }
  const addToQueue = () => {
    if (!target.itemId) return
    // Keep the item's current `seg` status and flag it for the queue; the event carries no seg_id,
    // so it is about `default_seg`
    const current = state?.find((r) => r.item_id === target.itemId && r.target === 'seg' && (r.seg_id ?? 'imported') === defaultSeg)?.status ?? 'not_reviewed'
    append.mutate(
      { item_id: target.itemId, case_id: target.caseId, target: 'seg', status: current, priority: 'medium', comment: '', add_to_queue: true },
      {
        onSuccess: () => toast({ message: t('cohort.menu.queued'), tone: 'ok' }),
        onError: (e) => {
          if (!(e instanceof ReviewerCancelled)) toast({ message: t('common.saveFailed'), tone: 'error' })
        },
      },
    )
  }
  return (
    <Menu.Root open onOpenChange={(o) => !o && close()} modal={false}>
      <Menu.Trigger asChild>
        <span aria-hidden style={{ position: 'fixed', left: target.x, top: target.y, width: 1, height: 1 }} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="overlay menu" align="start" sideOffset={2}>
          <Menu.Label className="menu-label">{target.label}</Menu.Label>
          {hasValue ? (
            <Menu.Item className="menu-item" onSelect={copy}>
              <Icon spec={codicon('copy')} />
              {t('cohort.menu.copy')}
            </Menu.Item>
          ) : null}
          {hasValue && target.column ? (
            <Menu.Item className="menu-item" onSelect={() => addVarValue(target.column!, String(target.value))}>
              <Icon spec={codicon('filter')} />
              {t('cohort.menu.filter')}
            </Menu.Item>
          ) : null}
          {editable ? (
            <>
              <Menu.Item className="menu-item" onSelect={() => setEditing({ caseId: target.caseId, scanIdx: target.scanIdx, column: target.column ?? '' })}>
                <Icon spec={codicon('edit')} />
                {t('cohort.edit.edit')}
              </Menu.Item>
              <Menu.Item className="menu-item" onSelect={fill}>
                <Icon spec={codicon('fold-down')} />
                {t(hasValue ? 'cohort.edit.fill' : 'cohort.edit.clear')}
              </Menu.Item>
              <Menu.Item className="menu-item" onSelect={paste}>
                <Icon spec={codicon('clippy')} />
                {t('cohort.edit.paste')}
              </Menu.Item>
            </>
          ) : null}
          {target.column ? (
            <Menu.Item className="menu-item" onSelect={() => setSummary(target.column)}>
              <Icon spec={codicon('graph')} />
              {t('cohort.menu.summary')}
            </Menu.Item>
          ) : null}
          <Menu.Item className="menu-item" onSelect={() => setCompare(target.caseId)}>
            <Icon spec={codicon('diff')} />
            {t('cohort.menu.compare')}
          </Menu.Item>
          <Menu.Item className="menu-item" onSelect={() => setTimeline(target.caseId)}>
            <Icon spec={codicon('timeline-view-icon')} />
            {t('cohort.menu.timeline')}
          </Menu.Item>
          {target.itemId ? (
            <Menu.Item className="menu-item" onSelect={() => setTags(target.itemId)}>
              <Icon spec={codicon('symbol-key')} />
              {t('cohort.menu.tags')}
            </Menu.Item>
          ) : null}
          {target.itemId ? (
            <Menu.Item className="menu-item" onSelect={() => openItem(target.caseId, target.itemId, true)}>
              <Icon spec={codicon('eye')} />
              {t('cohort.menu.open')}
            </Menu.Item>
          ) : null}
          {target.itemId && registry.allowed({ writes: true }) ? (
            <Menu.Item className="menu-item" onSelect={addToQueue}>
              <Icon spec={codicon('checklist')} />
              {t('cohort.menu.queue')}
            </Menu.Item>
          ) : null}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}
