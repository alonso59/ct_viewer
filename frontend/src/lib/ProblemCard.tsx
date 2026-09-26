// UI-18: every error shows its cause (`detail`) and its next actions (`actions[]`) as buttons.
// The title comes from the problem code in plain words; the raw message is never the title and
// the slug is not shown as a chip (AUD-A2-07, AUD-A3-03); it stays in `data-problem` and the
// title's tooltip for support.
import { useTranslation } from 'react-i18next'

import { ProblemError, parseAction } from '../api/problem'
import { Icon, codicon } from '../theme'

/** Actions the caller can perform; others are shown as plain hints (e.g. `configure:…`) */
export type ActionHandlers = Partial<Record<string, (arg: string | null) => void>>

export function ProblemCard({ error, onAction, labels }: { error: unknown; onAction?: ActionHandlers; labels?: Partial<Record<string, string>> }) {
  const { t } = useTranslation()
  const p = error instanceof ProblemError ? error : null
  const raw = error instanceof Error ? error.message : String(error)
  const title = p ? (p.generic ? t(`problemTitle.${p.type}`, { defaultValue: p.title }) : p.title) : t('problemTitle.unknown')
  const detail = p ? p.detail : raw
  return (
    <div className="error-card" role="alert" data-problem={p?.type}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: 'var(--error)', display: 'inline-flex' }}>
          <Icon spec={codicon('error')} />
        </span>
        <strong title={p?.type}>{title}</strong>
      </div>
      {detail ? <div style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>{detail}</div> : null}
      {p?.actions.length ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
          {p.actions.map((a) => {
            const { name, arg } = parseAction(a)
            const run = onAction?.[name]
            const label = labels?.[name] ?? t(`problemAction.${name}`, { arg: arg ?? '' })
            return run ? (
              <button key={a} type="button" className="btn" onClick={() => run(arg)}>
                {label}
              </button>
            ) : (
              <span key={a} className="badge">{label}</span>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
