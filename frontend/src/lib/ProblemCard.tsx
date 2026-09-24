// UI-18: every error shows its cause (`detail`) and its next actions (`actions[]`) as buttons.
import { useTranslation } from 'react-i18next'

import { ProblemError, parseAction } from '../api/problem'
import { Icon, codicon } from '../theme'

/** Actions the caller can perform; others are shown as plain hints (e.g. `configure:…`) */
export type ActionHandlers = Partial<Record<string, (arg: string | null) => void>>

export function ProblemCard({ error, onAction }: { error: unknown; onAction?: ActionHandlers }) {
  const { t } = useTranslation()
  const p = error instanceof ProblemError ? error : null
  const title = p?.title ?? (error instanceof Error ? error.message : String(error))
  return (
    <div className="error-card" role="alert">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: 'var(--error)', display: 'inline-flex' }}>
          <Icon spec={codicon('error')} />
        </span>
        <strong>{title}</strong>
        {p ? <span className="badge mono">{p.type}</span> : null}
      </div>
      {p?.detail ? <div style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>{p.detail}</div> : null}
      {p?.actions.length ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
          {p.actions.map((a) => {
            const { name, arg } = parseAction(a)
            const run = onAction?.[name]
            const label = t(`problemAction.${name}`, { arg: arg ?? '' })
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
