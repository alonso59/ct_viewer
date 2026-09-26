// Test result line, test override and results table shared by the statistics views (ANA-04/05)
import { useTranslation } from 'react-i18next'

import type { ResultRow, TestChoice } from '../../../api'
import { fmtInt, fmtNum } from '../../../lib'

export type TestMode = 'auto' | 'default' | 'alternative'

export const fmtP = (p: number | null | undefined) => (p == null ? '—' : p < 0.001 ? p.toExponential(1) : fmtNum(p))

export function TestSwitch({ value, onChange }: { value: TestMode; onChange: (m: TestMode) => void }) {
  const { t } = useTranslation()
  return (
    <div className="seg" role="group" aria-label={t('dashboard.test.label')}>
      {(['auto', 'default', 'alternative'] as const).map((m) => (
        <button key={m} type="button" aria-pressed={value === m} onClick={() => onChange(m)}>{t(`dashboard.test.${m}`)}</button>
      ))}
    </div>
  )
}

/** Chosen test + reason (ANA-04) and the selected feature's statistics */
export function TestResult({ choice, row }: { choice: TestChoice; row: ResultRow | null }) {
  const { t } = useTranslation()
  const test = row?.test ?? choice.default_test
  return (
    <div className="db-test">
      <strong>{test ? t(`dashboard.testName.${test}`) : t('dashboard.test.none')}</strong>
      <span className="muted">{row?.reason ?? choice.reason}</span>
      {row ? (
        <span className="num">
          {t('dashboard.test.stats', {
            n: fmtInt(row.n),
            effect: row.effect != null ? fmtNum(row.effect) : '—',
            effectName: row.effect_name ? t(`dashboard.effect.${row.effect_name}`) : '',
            p: fmtP(row.p),
            q: fmtP(row.q),
          })}
        </span>
      ) : null}
    </div>
  )
}

/** Results for every feature, sorted by q then |effect| (ANA-05); a row picks the feature */
export function ResultsTable({ rows, selected, onPick }: { rows: ResultRow[]; selected: string | null; onPick: (r: ResultRow) => void }) {
  const { t } = useTranslation()
  const sorted = [...rows].sort((a, b) => (a.q ?? 2) - (b.q ?? 2) || Math.abs(b.effect ?? 0) - Math.abs(a.effect ?? 0))
  return (
    <table className="table">
      <thead>
        <tr>
          <th>{t('dashboard.feature')}</th>
          <th className="num">{t('dashboard.col.n')}</th>
          <th className="num">{t('dashboard.col.effect')}</th>
          <th className="num">{t('dashboard.col.p')}</th>
          <th className="num">{t('dashboard.col.q')}</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => (
          <tr key={r.feature ?? ''} data-clickable="true" aria-selected={r.feature === selected || undefined} onClick={() => onPick(r)}>
            <td className="mono truncate" title={r.feature ?? undefined}>{(r.feature ?? '').replace(/^original_/, '')}</td>
            <td className="num">{fmtInt(r.n)}</td>
            <td className="num">{r.effect != null ? fmtNum(r.effect) : '—'}</td>
            <td className="num">{fmtP(r.p)}</td>
            <td className="num" style={{ color: r.q != null && r.q < 0.05 ? 'var(--ok)' : undefined }}>{fmtP(r.q)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
