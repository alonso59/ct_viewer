// Table and column actions (LBL-02, LBL-10): edit / delete menus and their dialogs. Delete hides:
// the events and the slug are kept, so a table or a column can be restored unchanged.
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, useLabelTables, useVariables, type LabelColumn, type LabelColumnIn, type LabelTable, type LabelTablePatch } from '../../api'
import { Dialog, ProblemCard } from '../../lib'
import { useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'

type Table = Pick<LabelTable, 'table_id' | 'name' | 'slug' | 'columns'>

/** PATCH the table and refresh everything labeling (tables, deleted tables, cells) */
function usePatch(pid: string, tid: string) {
  const qc = useQueryClient()
  const [error, setError] = useState<unknown>(null)
  const run = async (body: LabelTablePatch) => {
    try {
      setError(null)
      await api.patchLabelTable(pid, tid, body)
      await qc.invalidateQueries({ queryKey: keys.scope(pid, 'labeling') })
      return true
    } catch (e) {
      setError(e)
      return false
    }
  }
  return { run, error }
}

/** VAR-06 derived variables built on these label variables (directly or through another derived
 *  one): deleting the table or column breaks them (AUD-A5-08), so the dialog names them */
function useDerivedUsers(pid: string, uses: (source: string) => boolean): string[] {
  const vars = useVariables(pid).data ?? []
  const defs = vars.flatMap((v) => (v.definition ? [{ name: v.name, sources: v.definition.op === 'dominant' ? v.definition.sources : [v.definition.source] }] : []))
  const hit = new Set<string>()
  for (let grew = true; grew; ) {
    grew = false
    for (const d of defs)
      if (!hit.has(d.name) && d.sources.some((s) => uses(s) || hit.has(s))) {
        hit.add(d.name)
        grew = true
      }
  }
  return [...hit].sort()
}

function DerivedWarning({ names }: { names: string[] }) {
  const { t } = useTranslation()
  if (!names.length) return null
  return (
    <div className="error-card" role="alert">
      {t('lbl.derivedUsers', { count: names.length, list: names.join(', ') })}
    </div>
  )
}

const closeTab = (tid: string) => useWorkbench.getState().dock?.getPanel(`labeling:${tid}`)?.api.close()

function Footer({ onCancel, onOk, ok, disabled, danger }: { onCancel: () => void; onOk: () => void; ok: string; disabled?: boolean; danger?: boolean }) {
  const { t } = useTranslation()
  return (
    <>
      <button type="button" className="btn" onClick={onCancel}>{t('common.cancel')}</button>
      <button type="button" className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} disabled={disabled} onClick={onOk}>{ok}</button>
    </>
  )
}

/** Rename the table; restore its deleted columns (LBL-02/10) */
function EditTableDialog({ pid, table, onClose }: { pid: string; table: Table; onClose: () => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState(table.name)
  const { run, error } = usePatch(pid, table.table_id)
  const deleted = (table.columns ?? []).filter((c) => c.hidden)
  const save = async () => {
    if (name.trim() === table.name || (await run({ name: name.trim() }))) onClose()
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('lbl.editTable')} icon={codicon('table')} footer={<Footer onCancel={onClose} onOk={() => void save()} ok={t('common.save')} disabled={!name.trim()} />}>
      <div className="lbl-form">
        <label className="field">
          <span className="field-label">{t('lbl.tableName')}</span>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
          <span className="muted lbl-small">{t('lbl.renameHelp')}</span>
        </label>
        {deleted.length ? (
          <div className="field">
            <span className="field-label">{t('lbl.deletedColumns')}</span>
            <ul className="lbl-restore-list">
              {deleted.map((c) => (
                <li key={c.column_id}>
                  <span>{c.name}</span>
                  <button type="button" className="btn btn-sm" onClick={() => void run({ columns: [{ column_id: c.column_id, name: c.name, hidden: false }] })}>
                    {t('lbl.restore')}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {error ? <ProblemCard error={error} /> : null}
      </div>
    </Dialog>
  )
}

function DeleteTableDialog({ pid, table, onClose }: { pid: string; table: Table; onClose: () => void }) {
  const { t } = useTranslation()
  const { run, error } = usePatch(pid, table.table_id)
  const users = useDerivedUsers(pid, (s) => s.startsWith(`lbl.${table.slug}.`))
  const del = async () => {
    if (!(await run({ hidden: true }))) return
    onClose()
    closeTab(table.table_id)
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('lbl.deleteTableTitle', { name: table.name })} icon={codicon('trash')} footer={<Footer onCancel={onClose} onOk={() => void del()} ok={t('lbl.deleteTable')} danger />}>
      <p>{t('lbl.deleteTableHelp')}</p>
      <DerivedWarning names={users} />
      {error ? <ProblemCard error={error} /> : null}
    </Dialog>
  )
}

const num = (s: string) => (s.trim() === '' ? null : Number(s.replace(',', '.')))

/** Edit a column's name, description and type settings; the type itself is fixed (LBL-02) */
function EditColumnDialog({ pid, tid, col, onClose }: { pid: string; tid: string; col: LabelColumn; onClose: () => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState(col.name)
  const [description, setDescription] = useState(col.description ?? '')
  const [levels, setLevels] = useState((col.levels ?? []).join(', '))
  const [unit, setUnit] = useState(col.unit ?? '')
  const [min, setMin] = useState(col.min == null ? '' : String(col.min))
  const [max, setMax] = useState(col.max == null ? '' : String(col.max))
  const { run, error } = usePatch(pid, tid)
  const lv = levels.split(',').map((x) => x.trim()).filter(Boolean)
  const bad = !name.trim() || (col.type === 'category' && !col.ref && !lv.length) || [min, max].some((x) => x.trim() !== '' && Number.isNaN(num(x)))
  const save = async () => {
    const c: LabelColumnIn = { column_id: col.column_id, name: name.trim(), description: description.trim() || null }
    if (col.type === 'category' && !col.ref) c.levels = lv
    if (col.type === 'number') Object.assign(c, { unit: unit.trim() || null, min: num(min), max: num(max) })
    if (await run({ columns: [c] })) onClose()
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('lbl.editColumn')} footer={<Footer onCancel={onClose} onOk={() => void save()} ok={t('common.save')} disabled={bad} />}>
      <div className="lbl-form">
        <label className="field">
          <span className="field-label">{t('lbl.colNameEdit')}</span>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
          <span className="muted lbl-small">{col.ref ? t('lbl.refOf', { name: col.ref }) : t('lbl.colTypeFixed', { type: t(`lbl.type.${col.type}`) })}</span>
        </label>
        <label className="field">
          <span className="field-label">{t('lbl.description')}</span>
          <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        {col.type === 'category' && !col.ref ? (
          <label className="field">
            <span className="field-label">{t('lbl.levels')}</span>
            <input className="input" placeholder={t('lbl.levelsHint')} value={levels} onChange={(e) => setLevels(e.target.value)} />
            <span className="muted lbl-small">{t('lbl.levelsKeep')}</span>
          </label>
        ) : null}
        {col.type === 'number' ? (
          <div className="lbl-row">
            <label className="field">
              <span className="field-label">{t('lbl.unit')}</span>
              <input className="input lbl-unit" value={unit} onChange={(e) => setUnit(e.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">{t('lbl.min')}</span>
              <input className="input lbl-unit" inputMode="decimal" value={min} onChange={(e) => setMin(e.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">{t('lbl.max')}</span>
              <input className="input lbl-unit" inputMode="decimal" value={max} onChange={(e) => setMax(e.target.value)} />
            </label>
          </div>
        ) : null}
        {error ? <ProblemCard error={error} /> : null}
      </div>
    </Dialog>
  )
}

function DeleteColumnDialog({ pid, tid, col, onClose }: { pid: string; tid: string; col: LabelColumn; onClose: () => void }) {
  const { t } = useTranslation()
  const { run, error } = usePatch(pid, tid)
  const slug = useLabelTables(pid).data?.find((x) => x.table_id === tid)?.slug
  const users = useDerivedUsers(pid, (s) => s === `lbl.${slug}.${col.slug}`)
  const del = async () => {
    if (await run({ columns: [{ column_id: col.column_id, name: col.name, hidden: true }] })) onClose()
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('lbl.deleteColumnTitle', { name: col.name })} icon={codicon('trash')} footer={<Footer onCancel={onClose} onOk={() => void del()} ok={t('lbl.deleteColumn')} danger />}>
      <p>{t('lbl.deleteColumnHelp')}</p>
      <DerivedWarning names={users} />
      {error ? <ProblemCard error={error} /> : null}
    </Dialog>
  )
}

function Trigger({ label }: { label: string }) {
  return (
    <Menu.Trigger className="icon-btn lbl-menu-btn" aria-label={label} title={label}>
      <Icon spec={codicon('ellipsis')} />
    </Menu.Trigger>
  )
}

/** "…" menu of a table: Edit table…, Delete table… */
export function TableMenu({ pid, table }: { pid: string; table: Table }) {
  const { t } = useTranslation()
  const [dialog, setDialog] = useState<'edit' | 'delete' | null>(null)
  return (
    <>
      <Menu.Root modal={false}>
        <Trigger label={t('lbl.tableActions', { name: table.name })} />
        <Menu.Portal>
          <Menu.Content className="overlay menu" sideOffset={4} align="end">
            <Menu.Item className="menu-item" onSelect={() => setDialog('edit')}>{t('lbl.editTableMenu')}</Menu.Item>
            <Menu.Separator className="menu-sep" />
            <Menu.Item className="menu-item" onSelect={() => setDialog('delete')}>{t('lbl.deleteTableMenu')}</Menu.Item>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      {dialog === 'edit' ? <EditTableDialog pid={pid} table={table} onClose={() => setDialog(null)} /> : null}
      {dialog === 'delete' ? <DeleteTableDialog pid={pid} table={table} onClose={() => setDialog(null)} /> : null}
    </>
  )
}

/** "…" menu of a column header: Edit column…, Delete column… */
export function ColumnMenu({ pid, tid, col }: { pid: string; tid: string; col: LabelColumn }) {
  const { t } = useTranslation()
  const [dialog, setDialog] = useState<'edit' | 'delete' | null>(null)
  return (
    <>
      <Menu.Root modal={false}>
        <Trigger label={t('lbl.columnActions', { name: col.name })} />
        <Menu.Portal>
          <Menu.Content className="overlay menu" sideOffset={4} align="end">
            <Menu.Item className="menu-item" onSelect={() => setDialog('edit')}>{t('lbl.editColumnMenu')}</Menu.Item>
            <Menu.Separator className="menu-sep" />
            <Menu.Item className="menu-item" onSelect={() => setDialog('delete')}>{t('lbl.deleteColumnMenu')}</Menu.Item>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      {dialog === 'edit' ? <EditColumnDialog pid={pid} tid={tid} col={col} onClose={() => setDialog(null)} /> : null}
      {dialog === 'delete' ? <DeleteColumnDialog pid={pid} tid={tid} col={col} onClose={() => setDialog(null)} /> : null}
    </>
  )
}

/** LBL-10: deleted tables with Restore */
export function DeletedTables({ pid, tables }: { pid: string; tables: Table[] }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<unknown>(null)
  if (!tables.length) return null
  const restore = async (tid: string) => {
    try {
      setError(null)
      await api.patchLabelTable(pid, tid, { hidden: false })
      await qc.invalidateQueries({ queryKey: keys.labelTables(pid) })
    } catch (e) {
      setError(e)
    }
  }
  return (
    <div className="lbl-deleted">
      <button type="button" className="sidebar-section-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon spec={codicon(open ? 'chevron-down' : 'chevron-right')} />
        {t('lbl.deletedTables', { n: tables.length })}
      </button>
      {open ? (
        <ul className="lbl-restore-list">
          {tables.map((x) => (
            <li key={x.table_id}>
              <span>{x.name}</span>
              <button type="button" className="btn btn-sm" onClick={() => void restore(x.table_id)}>{t('lbl.restore')}</button>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <ProblemCard error={error} /> : null}
    </div>
  )
}
