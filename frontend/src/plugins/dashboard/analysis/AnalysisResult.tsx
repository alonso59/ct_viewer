// DB-08 result: chosen test + reason (ANA-04), groups (ANA-06), recommendations (ANA-08),
// results sorted by q (ANA-05), descriptives (ANA-07), contingency (balance), exports (ANA-09).
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, type Analysis, type AnalysisExportFile, type LabelDef, type Recommendation, type ResultRow } from '../../../api'
import { fmtInt } from '../../../lib'
import { toast, useWorkbench } from '../../../shell'
import { Icon, codicon } from '../../../theme'
import { useDashboardStore } from '../store'
import { Q_SIGNIFICANT, fmtP, fmtStat, sortResults, viewForResult } from './model'

const EXPORTS: AnalysisExportFile[] = ['tidy', 'results', 'descriptives', 'spec']

function download(name: string, blob: Blob) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

function ExportMenu({ analysis }: { analysis: Analysis }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const base = (analysis.spec.name || analysis.analysis_id).replace(/[^\w.-]+/g, '_')
  const run = async (file: AnalysisExportFile) => {
    try {
      const blob = await api.exportAnalysis(pid, analysis.analysis_id, file)
      download(file === 'spec' ? `${base}_spec.json` : `${base}_${file}.csv`, blob)
    } catch {
      toast({ message: t('analysis.exportFailed'), tone: 'error' })
    }
  }
  return (
    <Menu.Root>
      <Menu.Trigger className="btn btn-sm">
        <Icon spec={codicon('export')} />
        {t('analysis.export')}
        <Icon spec={codicon('chevron-down')} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="overlay menu" sideOffset={4} align="end">
          {EXPORTS.map((f) => (
            <Menu.Item key={f} className="menu-item" onSelect={() => void run(f)}>
              {t(`analysis.exportFile.${f}`)}
            </Menu.Item>
          ))}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}

function Recommendations({ recs, runId }: { recs: Recommendation[]; runId: string }) {
  const { t } = useTranslation()
  return (
    <section className="an-section" aria-label={t('analysis.recommendations')}>
      <div className="section-title an-title">
        {t('analysis.recommendations')}
        <span className="count">{recs.length}</span>
      </div>
      {recs.length === 0 ? <div className="muted an-help">{t('analysis.noRecommendations')}</div> : null}
      <ul className="an-recs">
        {recs.map((r, i) => (
          <li key={`${r.code}-${i}`}>
            <button
              type="button"
              className="an-rec"
              title={t('analysis.openView')}
              onClick={() => useDashboardStore.getState().focusView(runId, r.view, r.params ?? {})}
            >
              <Icon spec={codicon('lightbulb')} />
              <span className="an-rec-body">
                <span className="mono an-rec-code">{r.code}</span>
                <span>{r.message}</span>
              </span>
              <Icon spec={codicon('link-external')} />
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ResultsTable({ rows, selected, onSelect }: { rows: ResultRow[]; selected: string | null; onSelect: (r: ResultRow) => void }) {
  const { t } = useTranslation()
  return (
    <div className="an-scroll">
      <table className="table an-table">
        <thead>
          <tr>
            <th>{t('analysis.col.feature')}</th>
            <th className="num">{t('analysis.col.n')}</th>
            <th className="num">{t('analysis.col.effect')}</th>
            <th className="num">{t('analysis.col.p')}</th>
            <th className="num">{t('analysis.col.q')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const sig = r.q != null && r.q < Q_SIGNIFICANT
            return (
              <tr key={r.feature ?? r.test ?? ''} data-clickable="true" aria-selected={r.feature === selected} onClick={() => onSelect(r)} title={r.reason}>
                <td className="mono an-feature">{r.feature}</td>
                <td className="num">{fmtInt(r.n)}</td>
                <td className="num" title={r.effect_name ? t(`analysis.effect.${r.effect_name}`) : undefined}>{fmtStat(r.effect)}</td>
                <td className="num">{fmtP(r.p)}</td>
                <td className="num" style={sig ? { color: 'var(--ok)', fontWeight: 600 } : undefined}>{fmtP(r.q)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** One feature's rows per group; `feature = null` lists every feature (Explore has no results) */
function Descriptives({ analysis, feature }: { analysis: Analysis; feature: string | null }) {
  const { t } = useTranslation()
  const all = feature === null
  const rows = all ? analysis.descriptives : analysis.descriptives.filter((d) => d.feature === feature)
  return (
    <section className="an-section">
      <div className="section-title an-title">
        {t('analysis.descriptives')}
        {all ? null : <span className="mono an-count">{feature}</span>}
      </div>
      <div className="an-scroll">
        <table className="table an-table">
          <thead>
            <tr>
              {all ? <th>{t('analysis.col.feature')}</th> : null}
              <th>{t('analysis.col.group')}</th>
              <th className="num">{t('analysis.col.n')}</th>
              <th className="num">{t('analysis.col.missing')}</th>
              <th className="num">{t('analysis.col.median')}</th>
              <th className="num">{t('analysis.col.iqr')}</th>
              <th className="num">{t('analysis.col.mean')}</th>
              <th className="num">{t('analysis.col.sd')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={`${d.feature}|${d.group}`} className={d.excluded ? 'muted' : undefined}>
                {all ? <td className="mono an-feature">{d.feature}</td> : null}
                <td>{d.group}</td>
                <td className="num">{fmtInt(d.n)}</td>
                <td className="num">{fmtInt(d.missing)}</td>
                <td className="num">{fmtStat(d.median)}</td>
                <td className="num">{fmtStat(d.iqr)}</td>
                <td className="num">{fmtStat(d.mean)}</td>
                <td className="num">{fmtStat(d.sd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Contingency({ analysis, runId }: { analysis: Analysis; runId: string }) {
  const { t } = useTranslation()
  const b = analysis.balance
  if (!b) return null
  const cell = (row: string, col: string) => b.cells.find((c) => c.row === row && c.col === col)
  return (
    <section className="an-section">
      <div className="section-title an-title">
        {t('analysis.balanceTable')}
        <button
          type="button"
          className="icon-btn an-count"
          title={t('analysis.openView')}
          aria-label={t('analysis.openView')}
          onClick={() => useDashboardStore.getState().focusView(runId, 'balance', { variable: b.variable, other: b.other })}
        >
          <Icon spec={codicon('link-external')} />
        </button>
      </div>
      <div className="an-scroll">
        <table className="table an-table">
          <thead>
            <tr>
              <th className="mono">{t('analysis.crossHeader', { variable: b.variable, other: b.other })}</th>
              {b.cols.map((c) => (
                <th key={c} className="num">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {b.rows.map((r) => (
              <tr key={r}>
                <td>{r}</td>
                {b.cols.map((c) => {
                  const x = cell(r, c)
                  return (
                    <td key={c} className="num" title={t('analysis.cellTitle', { row: r, col: c, n: x?.n ?? 0 })}>
                      {fmtInt(x?.n ?? 0)}
                      {x?.expected != null ? <span className="muted an-expected">{t('analysis.expected', { value: fmtStat(x.expected) })}</span> : null}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="an-kv">
        <span>{b.result.test ? t(`analysis.test.${b.result.test}`) : null}</span>
        <span className="muted">{t('analysis.col.statistic')}</span>
        <span className="num">{fmtStat(b.result.statistic)}</span>
        <span className="muted">{t('analysis.col.p')}</span>
        <span className="num">{fmtP(b.result.p)}</span>
        <span className="muted">{b.result.effect_name ? t(`analysis.effect.${b.result.effect_name}`) : null}</span>
        <span className="num">{fmtStat(b.result.effect)}</span>
      </div>
    </section>
  )
}

export function AnalysisResult({ analysis, runId, labels }: { analysis: Analysis; runId: string; labels: LabelDef[] }) {
  const { t } = useTranslation()
  const { spec, choice, unit } = analysis
  const results = useMemo(() => sortResults(analysis.results.filter((r) => r.feature)), [analysis.results])
  const [picked, setPicked] = useState<string | null>(null)
  const feature = picked ?? results[0]?.feature ?? null
  const tested = results.filter((r) => r.q != null).length
  const significant = results.filter((r) => r.q != null && r.q < Q_SIGNIFICANT).length
  const labelName = labels.find((l) => l.value === unit.label)?.name ?? String(unit.label)
  const testName = (x: string | null | undefined) => (x ? t(`analysis.test.${x}`) : '')

  const onSelect = (r: ResultRow) => {
    setPicked(r.feature)
    const view = viewForResult(spec.question)
    if (view && r.feature && spec.variable) useDashboardStore.getState().focusView(runId, view, { variable: spec.variable, feature: r.feature })
  }

  return (
    <div className="an-result">
      <div className="an-result-head">
        <strong>{spec.name || t(`analysis.question.${spec.question}`)}</strong>
        <span style={{ flex: 1 }} />
        <ExportMenu analysis={analysis} />
      </div>
      <div className="an-kv">
        <span className="muted">{t('analysis.choice')}</span>
        <span>
          {choice.n_default && choice.n_alternative
            ? t('analysis.choiceMix', { def: testName(choice.default_test), nDef: choice.n_default, alt: testName(choice.alternative_test), nAlt: choice.n_alternative })
            : testName(choice.n_alternative ? choice.alternative_test : choice.default_test) || t('analysis.question.explore')}
        </span>
        <span className="muted">{t('analysis.reason')}</span>
        <span>{choice.reason}</span>
      </div>
      <div className="muted an-help">
        {t('analysis.unitSummary', {
          rows: unit.n_rows,
          cases: unit.n_cases,
          label: labelName,
          scope: unit.scope,
          phase: unit.phase ? t('analysis.unitPhase', { phase: unit.phase }) : '',
        })}
        {unit.n_variable_missing ? ` · ${t('analysis.missingVariable', { count: unit.n_variable_missing })}` : ''}
      </div>
      {analysis.groups.length ? (
        <div className="an-groups" aria-label={t('analysis.groups')}>
          {analysis.groups.map((g) => (
            <span key={g.level} className="badge" data-tone={g.excluded ? 'warn' : undefined}>
              {t(g.excluded ? 'analysis.groupExcluded' : 'analysis.groupN', { level: g.level, n: g.n })}
            </span>
          ))}
        </div>
      ) : null}
      <Recommendations recs={analysis.recommendations} runId={runId} />
      <Contingency analysis={analysis} runId={runId} />
      {results.length && spec.question !== 'balance' ? (
        <section className="an-section" aria-label={t('analysis.results')}>
          <div className="section-title an-title">
            {t('analysis.results')}
            <span className="muted an-count">{t('analysis.resultsCount', { significant, tested })}</span>
          </div>
          <ResultsTable rows={results} selected={feature} onSelect={onSelect} />
        </section>
      ) : null}
      {spec.question === 'explore' && analysis.descriptives.length ? <Descriptives analysis={analysis} feature={null} /> : null}
      {spec.question !== 'explore' && feature ? <Descriptives analysis={analysis} feature={feature} /> : null}
      {spec.question !== 'explore' && !feature && results.length ? <div className="muted an-help">{t('analysis.descriptivesHint')}</div> : null}
    </div>
  )
}
