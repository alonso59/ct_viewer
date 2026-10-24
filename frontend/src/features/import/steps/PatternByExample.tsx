// SRC-17 pattern by example: one real image path split into chips; the user says which piece is
// the case (scan, side, channel), then picks that image's mask in the browser. The `pattern` and
// `mask_template` options are generated from that; the raw fields stay under "Advanced".
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { NiftiOptions } from '../../../api'
import { Icon, codicon } from '../../../theme'
import { buildPattern, maskFor, matches, rolesFrom, ROLES, templatedMasks, templateFrom, tokenize, type Role } from '../byExample'
import { FolderBrowser } from '../FolderBrowser'
import { segments, stemOf, subjectOf } from '../patternSuggest'

// SRC-17 highlight colours: the categorical palette, fixed per group (--cat-1 is the accent blue)
export const GROUP_COLOR: Record<string, string> = { case_id: 'var(--cat-2)', scan_idx: 'var(--cat-4)', channel: 'var(--cat-6)', side: 'var(--cat-5)' }
const EXAMPLES = 3

/** A sampled path with the pattern's groups coloured; null when the pattern does not match it */
export function Highlight({ pattern, path }: { pattern: string; path: string }) {
  const parts = segments(pattern, subjectOf(pattern, path))
  if (!parts) return null
  return (
    <span className="mono pattern-ex">
      {parts.map((x, k) =>
        x.group ? <span key={k} className="pattern-group" style={{ color: GROUP_COLOR[x.group] }} title={x.group}>{x.text}</span> : <span key={k} className="muted">{x.text}</span>,
      )}
    </span>
  )
}

export function PatternByExample({ root, stems, value, onChange }: { root: string | null; stems: string[]; value: NiftiOptions; onChange: (v: NiftiOptions) => void }) {
  const { t } = useTranslation()
  const { pattern, mask_template: template } = value
  const masks = pattern && template ? templatedMasks(pattern, template, stems) : new Set<string>()
  const images = stems.filter((s) => !masks.has(s))
  const [pick, setPick] = useState<string | null>(null)
  const path = pick !== null && images.includes(pick) ? pick : (images[0] ?? '')
  const tokens = tokenize(path)
  // the user's own marks while they still give the current pattern; otherwise read from the pattern
  const [own, setOwn] = useState<{ path: string; roles: Role[] } | null>(null)
  const roles = own?.path === path && (buildPattern(tokens, own.roles) ?? undefined) === pattern ? own.roles : rolesFrom(pattern, path, tokens)
  const [browse, setBrowse] = useState<string | null>(null)
  const [maskError, setMaskError] = useState<string | null>(null)
  if (!path) return null

  const setRole = (i: number, role: Role) => {
    const next = roles.map((r, k) => (k === i ? role : r))
    setOwn({ path, roles: next })
    onChange({ ...value, pattern: buildPattern(tokens, next) ?? undefined })
  }
  const matched = pattern ? images.filter((s) => matches(pattern, s)) : []
  const exampleMask = pattern && template ? maskFor(pattern, template, path) : null
  const dir = root?.replace(/\/+$/, '') ?? ''
  const pickMask = (abs: string) => {
    const rel = abs.startsWith(`${dir}/`) ? abs.slice(dir.length + 1) : null
    const next = !pattern ? 'noCase' : rel === null ? 'outside' : templateFrom(pattern, path, rel)
    if (next === null || next === 'noCase' || next === 'outside') {
      setMaskError(t(`import.byExample.mask_${next ?? 'same'}`))
      return
    }
    setMaskError(null)
    setBrowse(null)
    onChange({ ...value, mask_template: next })
  }

  return (
    <div className="by-example">
      <span className="field-label">{t('import.byExample.title')}</span>
      <span className="muted small">{t('import.byExample.help')}</span>
      {images.length > 1 ? (
        <label className="field">
          <span className="muted small">{t('import.byExample.example')}</span>
          <select className="select mono" value={path} onChange={(e) => setPick(e.target.value)}>
            {images.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
      ) : null}
      <div className="example-tokens" role="group" aria-label={t('import.byExample.tokens')}>
        {tokens.map((tok, i) => (
          <span key={tok.at} className="example-token">
            <label className="example-chip" data-role={roles[i]} style={{ borderColor: GROUP_COLOR[roles[i] ?? ''] }}>
              <span className="mono" style={{ color: GROUP_COLOR[roles[i] ?? ''] }}>{tok.text}</span>
              <select className="example-role" value={roles[i]} aria-label={t('import.byExample.roleOf', { text: tok.text })} onChange={(e) => setRole(i, e.target.value as Role)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>{t(`import.byExample.role.${r}`)}</option>
                ))}
              </select>
            </label>
            {tok.sep ? <span className="mono muted">{tok.sep}</span> : null}
          </span>
        ))}
      </div>
      <div className="example-check" role="status">
        {pattern ? (
          <>
            <span className={matched.length === images.length ? 'text-ok' : 'text-warn'}>
              <Icon spec={codicon(matched.length === images.length ? 'pass' : 'warning')} /> {t('import.byExample.matches', { n: matched.length, total: images.length })}
            </span>
            {matched.slice(0, EXAMPLES).map((s) => (
              <Highlight key={s} pattern={pattern} path={s} />
            ))}
          </>
        ) : (
          <span className="muted">{t('import.byExample.noCase')}</span>
        )}
      </div>
      <div className="example-mask">
        <span className="small">
          {t('import.byExample.maskOf')} <span className="mono">{exampleMask ?? t('import.byExample.maskNone')}</span>
        </span>
        <span className="row wrap">
          <button type="button" className="btn btn-sm" disabled={!pattern} title={pattern ? undefined : t('import.byExample.mask_noCase')} onClick={() => setBrowse(browse === null ? dir : null)}>
            <Icon spec={codicon('layers')} />
            {t('import.byExample.chooseMask')}
          </button>
          {template ? (
            <button type="button" className="btn btn-sm" onClick={() => onChange({ ...value, mask_template: undefined })}>{t('import.byExample.clearMask')}</button>
          ) : null}
        </span>
      </div>
      {maskError ? <span className="small text-error" role="alert">{maskError}</span> : null}
      {browse !== null ? (
        <div className="example-browse">
          <FolderBrowser path={browse} onPath={(d) => setBrowse(d ?? dir)} onSelectFile={pickMask} />
          <span className="row wrap">
            <button type="button" className="btn btn-sm" disabled={browse === dir} onClick={() => pickMask(browse)}>
              <Icon spec={codicon('folder')} />
              {t('import.byExample.useFolder', { name: browse.slice(browse.lastIndexOf('/') + 1) })}
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setBrowse(null)}>{t('common.cancel')}</button>
          </span>
          <span className="muted small">{t('import.byExample.maskHelp', { example: stemOf(path.slice(path.lastIndexOf('/') + 1)) })}</span>
        </div>
      ) : null}
    </div>
  )
}
