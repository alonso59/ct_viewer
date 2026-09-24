// New label table / add columns (LBL-01/02): a level and typed columns, named freely or after the
// project labels.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'

import { api, keys, type LabelColumnIn, type LabelTable } from '../../api'
import { Dialog, ProblemCard } from '../../lib'
import { openEditor } from '../../shell'
import { Icon, codicon } from '../../theme'

const TYPES = ['bool', 'category', 'number', 'text', 'date'] as const
const LEVELS = ['case', 'scan', 'item'] as const

export interface Draft {
  name: string
  type: (typeof TYPES)[number]
  levels: string
  unit: string
}

const empty = (): Draft => ({ name: '', type: 'bool', levels: '', unit: '' })

export function ColumnsForm({ drafts, setDrafts, labels }: { drafts: Draft[]; setDrafts: (d: Draft[]) => void; labels: string[] }) {
  const { t } = useTranslation()
  const set = (i: number, patch: Partial<Draft>) => setDrafts(drafts.map((d, j) => (j === i ? { ...d, ...patch } : d)))
  return (
    <div className="lbl-colform">
      <datalist id="lbl-label-names">{labels.map((l) => <option key={l} value={l} />)}</datalist>
      {drafts.map((d, i) => (
        <div key={i} className="lbl-row">
          <input className="input input-sm" list="lbl-label-names" aria-label={t('lbl.colName')} placeholder={t('lbl.colName')} value={d.name} onChange={(e) => set(i, { name: e.target.value })} />
          <select className="input input-sm" aria-label={t('lbl.colType')} value={d.type} onChange={(e) => set(i, { type: e.target.value as Draft['type'] })}>
            {TYPES.map((x) => <option key={x} value={x}>{t(`lbl.type.${x}`)}</option>)}
          </select>
          {d.type === 'category' ? <input className="input input-sm" aria-label={t('lbl.levels')} placeholder={t('lbl.levelsHint')} value={d.levels} onChange={(e) => set(i, { levels: e.target.value })} /> : null}
          {d.type === 'number' ? <input className="input input-sm lbl-unit" aria-label={t('lbl.unit')} placeholder={t('lbl.unit')} value={d.unit} onChange={(e) => set(i, { unit: e.target.value })} /> : null}
          <button type="button" className="icon-btn" aria-label={t('lbl.removeCol')} onClick={() => setDrafts(drafts.filter((_, j) => j !== i))}><Icon spec={codicon('close')} /></button>
        </div>
      ))}
      <div><button type="button" className="btn btn-sm" onClick={() => setDrafts([...drafts, empty()])}>{t('lbl.addCol')}</button></div>
    </div>
  )
}

export const toColumns = (drafts: Draft[]): LabelColumnIn[] =>
  drafts
    .filter((d) => d.name.trim())
    .map((d) => ({ name: d.name.trim(), type: d.type, levels: d.type === 'category' ? d.levels.split(',').map((x) => x.trim()).filter(Boolean) : undefined, unit: d.type === 'number' && d.unit.trim() ? d.unit.trim() : undefined }))

export function NewTableDialog({ pid, labels, onClose }: { pid: string; labels: string[]; onClose: () => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [level, setLevel] = useState<(typeof LEVELS)[number]>('case')
  const [drafts, setDrafts] = useState<Draft[]>([empty()])
  const [error, setError] = useState<unknown>(null)
  const create = async () => {
    try {
      const tbl: LabelTable = await api.createLabelTable(pid, { name: name.trim(), level, columns: toColumns(drafts) })
      void qc.invalidateQueries({ queryKey: keys.labelTables(pid) })
      onClose()
      openEditor('labeling', { tableId: tbl.table_id })
    } catch (e) {
      setError(e)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('lbl.newTable')}
      icon={codicon('table')}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" disabled={!name.trim()} onClick={() => void create()}>{t('lbl.create')}</button>
        </>
      }
    >
      <div className="lbl-form">
        <label className="field">
          <span className="field-label">{t('lbl.tableName')}</span>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <div className="field">
          <span className="field-label">{t('lbl.levelLabel')}</span>
          <div className="seg" role="group" aria-label={t('lbl.levelLabel')}>
            {LEVELS.map((l) => <button key={l} type="button" aria-pressed={level === l} onClick={() => setLevel(l)}>{t(`lbl.level.${l}`)}</button>)}
          </div>
          <span className="muted lbl-small">{t(`lbl.levelHelp.${level}`)}</span>
        </div>
        <span className="field-label">{t('lbl.columns')}</span>
        <ColumnsForm drafts={drafts} setDrafts={setDrafts} labels={labels} />
        {error ? <ProblemCard error={error} /> : null}
      </div>
    </Dialog>
  )
}
