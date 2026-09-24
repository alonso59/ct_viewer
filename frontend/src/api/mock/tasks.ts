// Mock task catalog and task runs (API-42..47, TSK-*): the builtin radiomics task and the CI
// threshold plugin, enough for the Tasks view and preflight to work with VITE_API_MODE=mock.
import type { ItemRecord, PreflightResult, TaskInfo, TaskManifest, TaskSelection, TaskValidateResult } from '../types'

const threshold: TaskManifest = {
  manifest: 1,
  id: 'segment.threshold',
  version: '0.1.0',
  title: 'Threshold segmentation (test)',
  description: 'Fake segmentation for CI: voxels above a threshold become one label (TST-14).',
  kind: 'segmentation',
  input: 'items',
  outputs: ['masks'],
  requires: { modality: ['CT'], channels: null, seg: null },
  settings_schema: {
    type: 'object',
    properties: {
      threshold: { type: 'number', default: 0 },
      label: { type: 'integer', minimum: 1, maximum: 255, default: 1 },
      seg_id: { type: 'string', pattern: '^[a-z0-9][a-z0-9_-]{0,63}$' },
    },
  },
  defaults: {},
  runtime: { type: 'external', command: ['{python}', 'run.py', '{job_dir}'], entry: null, env_hint: 'any Python with numpy + nibabel' },
  resources: { gpu: 'none', max_batch: null, seconds_per_item: 1 },
  labels: { names: { '1': 'foreground' } },
  test_only: true,
}

const radiomics: TaskManifest = {
  manifest: 1,
  id: 'radiomics.pyradiomics',
  version: '1.0.0',
  title: 'Radiomics features (PyRadiomics)',
  description: 'IBSI-mapped PyRadiomics features per item and label (RADIOMICS.md). Settings: API-30.',
  kind: 'features',
  input: 'items',
  outputs: ['features'],
  requires: { modality: null, channels: null, seg: { labels: [] } },
  settings_schema: { type: 'object', additionalProperties: true },
  defaults: {},
  runtime: { type: 'builtin', entry: 'app.radiomics.worker:extract_unit', command: null, env_hint: null },
  resources: { gpu: 'none', max_batch: null, seconds_per_item: null },
  labels: null,
  test_only: false,
}

export const MOCK_TASKS: TaskInfo[] = [
  { manifest: radiomics, source: 'builtin', manifest_hash: 'sha256:mock-radiomics', available: true, unavailable_reason: null, runner_online: null, settings_schema_url: '/api/v1/radiomics/schema' },
  { manifest: threshold, source: 'plugins_root', manifest_hash: 'sha256:mock-threshold', available: true, unavailable_reason: null, runner_online: true, settings_schema_url: null },
]

/** TSK-02 (subset): defaults applied; unknown keys and out-of-range numbers are errors */
export function validateSettings(m: TaskManifest, raw: Record<string, unknown>): TaskValidateResult {
  const props = ((m.settings_schema as { properties?: Record<string, Record<string, unknown>> }).properties ?? {})
  const out: Record<string, unknown> = {}
  for (const [k, p] of Object.entries(props)) if ('default' in p) out[k] = p.default
  const issues: TaskValidateResult['issues'] = []
  for (const [k, v] of Object.entries(raw)) {
    const p = props[k]
    if (!p) {
      if (!(m.settings_schema as { additionalProperties?: boolean }).additionalProperties) issues.push({ loc: [k], msg: 'Unknown setting', rule: 'unknown', severity: 'error' })
      out[k] = v
      continue
    }
    if ((p.type === 'number' || p.type === 'integer') && typeof v === 'number') {
      if (typeof p.minimum === 'number' && v < p.minimum) issues.push({ loc: [k], msg: `Must be ≥ ${p.minimum}`, rule: 'range', severity: 'error' })
      if (typeof p.maximum === 'number' && v > p.maximum) issues.push({ loc: [k], msg: `Must be ≤ ${p.maximum}`, rule: 'range', severity: 'error' })
    }
    out[k] = v
  }
  const ok = issues.length === 0
  return { ok, issues, settings: ok ? out : null, settings_hash: ok ? `sha256:mock-${JSON.stringify(out).length}` : null }
}

/** TSK-04 over mock items */
export function preflight(m: TaskManifest, items: ItemRecord[], sel: TaskSelection, defaultSeg: string, hasDerived: boolean): PreflightResult {
  const seg = sel.seg_id ?? defaultSeg
  const missing: Record<string, number> = {}
  const ready: string[] = []
  for (const it of items) {
    let reason: string | null = null
    if (!it.image) reason = 'no image'
    else if (m.requires?.modality && it.modality && !m.requires.modality.includes(it.modality)) reason = `modality ${it.modality}`
    else if (m.requires?.seg && !(seg in it.masks)) reason = `no mask in ${seg}`
    if (reason) missing[reason] = (missing[reason] ?? 0) + 1
    else ready.push(it.item_id)
  }
  const needsDerived = m.outputs.some((o) => o === 'masks' || o === 'images') && !hasDerived
  return { n_selected: items.length, n_ready: ready.length, missing, suggestions: [], derived_root_required: needsDerived, ready_item_ids: ready }
}
