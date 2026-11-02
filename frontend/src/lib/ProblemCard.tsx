// Every error shows its cause (`detail`) and its next actions (`actions[]`) as buttons.
// The title comes from the problem code in plain words; the slug stays in `data-problem` and the title's tooltip.
import { useTranslation } from 'react-i18next'

import { ProblemError, parseAction } from '../api/problem'
import { Icon, codicon } from '../theme'

/** Actions the caller can perform; others are shown as plain hints (e.g. `configure:…`) */
export type ActionHandlers = Partial<Record<string, (arg: string | null) => void>>

/** `onRetry`: a Try again button (a failed load, a lost connection) */
export function ProblemCard({ error, onAction, labels, onRetry }: { error: unknown; onAction?: ActionHandlers; labels?: Partial<Record<string, string>>; onRetry?: () => void }) {
  const { t } = useTranslation()
  const p = error instanceof ProblemError ? error : null
  const raw = error instanceof Error ? error.message : String(error)
  // fetch() rejects with a TypeError when the server cannot be reached
  const offline = !p && error instanceof TypeError
  const title = p ? (p.generic ? t(`problemTitle.${p.type}`, { defaultValue: p.title }) : p.title) : t(offline ? 'problemTitle.offline' : 'problemTitle.unknown')
  const detail = p ? p.detail : offline ? t('problem.offlineDetail') : raw
  return (
    <div className="error-card" role="alert" data-problem={p?.type}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: 'var(--error)', display: 'inline-flex' }}>
          <Icon spec={codicon('error')} />
        </span>
        <strong title={p?.type}>{title}</strong>
      </div>
      {detail ? <div style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>{detail}</div> : null}
      {p?.actions.length || onRetry ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
          {onRetry ? <button type="button" className="btn" onClick={onRetry}>{t('problemAction.retry')}</button> : null}
          {(p?.actions ?? []).map((a) => {
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
