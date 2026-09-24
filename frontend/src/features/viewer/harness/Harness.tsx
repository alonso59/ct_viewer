// Harness page: the real viewer surface, tool bar, inspector sections and status items on the mock
// project, loading volumes straight from `.fixtures/` (served at /files by harness/vite.config.ts).
//   ?case=case_00001&item=<item_id>   a synthetic fixture item (default)
//   ?src=reference                    the TST-09 reference volume (make-reference.mjs)
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useCase, useCases, useProject, type ItemRecord } from '../../../api'
import { DEMO_PID } from '../../../api/mock/server'
import { useGlobalKeybindings, useWorkbench } from '../../../shell'
import { useViewerSync } from '../../../state'
import { applyTheme } from '../../../theme'
import { useLoadBudget } from '../budget'
import { defaultItem } from '../CaseEditor'
import { registerViewer } from '../index'
import { LayersSection, WindowSection } from '../Inspector'
import { useViewerLocal } from '../local'
import { isLayoutId } from '../model/layouts'
import { CursorStatus, WindowStatus } from '../StatusItems'
import { LayoutMenu, OverlayToggles, ResetAndSnapshot, ToolGroup, WindowPresets } from '../Tools'
import { ViewerSurface } from '../ViewerSurface'
import '../i18n'
import '../viewer.css'
import '../../../shell/shell.css'

registerViewer()
applyTheme('dark')

const params = new URLSearchParams(location.search)
const layoutParam = params.get('layout')
if (isLayoutId(layoutParam)) useViewerSync.setState({ layout: layoutParam })
const FILES = '/files'
const toUrl = (ref: string) => `${FILES}/synthetic/Dataset900/${ref.replace(/^[A-Z_]+:/, '')}`

/** TST-09 reference volume (NFR.md) as an item record */
const REFERENCE: ItemRecord = {
  item_id: 'reference',
  case_id: 'reference',
  scan_idx: '01',
  scope: 'complete',
  side: '-',
  patient_id: 'REF',
  modality: 'CT',
  import_id: 'harness',
  phase: { canonical: 'NP', raw: 'NP', source: 'none' },
  image: { ref: 'reference/reference_ct.nii.gz', format: 'nifti' },
  mask: { ref: 'reference/reference_seg.nii.gz', format: 'nifti' },
  geometry: { shape: [512, 512, 600], spacing: [0.78, 0.78, 0.8], dtype: 'int16', orientation: 'LPS' },
  labels_present: [1, 2, 3],
  status: 'active',
  warning_codes: [],
  extra: {},
}

function Keys() {
  useGlobalKeybindings()
  return null
}

export function Harness() {
  const { t } = useTranslation()
  const reference = params.get('src') === 'reference'
  const [caseId, setCaseId] = useState(params.get('case') ?? 'case_00001')
  const [itemId, setItemId] = useState<string | null>(params.get('item'))
  const cases = useCases(DEMO_PID)
  const kase = useCase(DEMO_PID, reference ? null : caseId)
  const project = useProject(DEMO_PID)
  const labels = useMemo(() => project.data?.label_map ?? [], [project.data])
  const loaded = useLoadBudget('harness', true)

  useEffect(() => {
    useWorkbench.setState({ pid: DEMO_PID, active: { type: 'case', caseId } })
    useViewerSync.setState({ viewerFocused: true })
  }, [caseId])

  // Bench hook (harness/bench.mjs)
  useEffect(
    () =>
      useViewerLocal.subscribe((s) => {
        ;(window as unknown as { __viewer?: unknown }).__viewer = s.active
      }),
    [],
  )

  const items = kase.data?.items ?? []
  const item = reference ? REFERENCE : (items.find((i) => i.item_id === itemId) ?? defaultItem(items))
  const imageUrl = reference ? `${FILES}/${REFERENCE.image?.ref}` : item?.image ? toUrl(item.image.ref) : ''
  const maskUrl = reference ? `${FILES}/${REFERENCE.mask?.ref}` : item?.mask ? toUrl(item.mask.ref) : undefined
  const harnessLabels = useMemo(() => (reference ? labels.map((l) => ({ ...l, visible: true })) : labels), [labels, reference])

  return (
    <div style={{ display: 'grid', gridTemplateRows: 'auto auto minmax(0, 1fr) 22px', height: '100%', background: 'var(--bg-editor)', color: 'var(--fg)' }}>
      <Keys />
      <div className="toolbar" style={{ height: 34, gap: 8 }}>
        <strong>{t('vw.harness.title')}</strong>
        <label className="field" style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
          <span className="field-label">{t('vw.harness.source')}</span>
          <select
            className="input input-sm"
            value={reference ? 'reference' : 'fixture'}
            onChange={(e) => {
              const sp = new URLSearchParams(location.search)
              if (e.target.value === 'reference') sp.set('src', 'reference')
              else sp.delete('src')
              location.search = sp.toString()
            }}
          >
            <option value="fixture">{t('vw.harness.fixture')}</option>
            <option value="reference">{t('vw.harness.reference')}</option>
          </select>
        </label>
        {!reference ? (
          <>
            <select className="input input-sm" value={caseId} onChange={(e) => (setCaseId(e.target.value), setItemId(null))}>
              {(cases.data ?? []).map((c) => (
                <option key={c.case_id} value={c.case_id}>
                  {c.case_id}
                </option>
              ))}
            </select>
            <select className="input input-sm" value={item?.item_id ?? ''} onChange={(e) => setItemId(e.target.value)}>
              {items.map((i) => (
                <option key={i.item_id} value={i.item_id}>
                  {i.item_id}
                </option>
              ))}
            </select>
          </>
        ) : null}
      </div>
      <div className="toolbar" style={{ height: 32 }}>
        <ToolGroup />
        <LayoutMenu />
        <OverlayToggles />
        <WindowPresets />
        <ResetAndSnapshot />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 280px', minHeight: 0 }}>
        <div className="case-editor" tabIndex={-1}>
          {item && imageUrl ? <ViewerSurface item={item} imageUrl={imageUrl} maskUrl={maskUrl} labels={harnessLabels} active loaded={loaded} /> : <div className="empty">{t('common.loading')}</div>}
        </div>
        <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 16, overflow: 'auto', borderLeft: '1px solid var(--border)' }}>
          <LayersSection />
          <WindowSection />
        </div>
      </div>
      <div className="statusbar" style={{ justifyContent: 'flex-end' }}>
        <CursorStatus />
        <WindowStatus />
      </div>
    </div>
  )
}
