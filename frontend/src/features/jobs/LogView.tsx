import { useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { LogLine } from '../../api'
import { toast } from '../../shell'
import { Icon, codicon } from '../../theme'

type Filter = 'all' | 'warn' | 'error'
const SHOWN: Record<Filter, ReadonlySet<LogLine['level']>> = {
  all: new Set(['info', 'warn', 'error']),
  warn: new Set(['warn', 'error']),
  error: new Set(['error']),
}

function color(l: LogLine) {
  if (l.level === 'error') return 'var(--error)'
  if (l.level === 'warn') return 'var(--warn)'
  return l.stream === 'stage' ? 'var(--fg-muted)' : undefined
}

/** A terminal-like list of log lines that follows new lines until the user scrolls up */
export function LogView({ lines }: { lines: LogLine[] }) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState<Filter>('all')
  const [follow, setFollow] = useState(true)
  const list = useRef<HTMLDivElement>(null)
  const shown = lines.filter((l) => SHOWN[filter].has(l.level))
  useLayoutEffect(() => {
    const el = list.current
    if (follow && el) el.scrollTop = el.scrollHeight
  }, [follow, shown.length, lines])
  const onScroll = () => {
    const el = list.current
    if (el) setFollow(el.scrollTop + el.clientHeight >= el.scrollHeight - 4)
  }
  const copy = async () => {
    const text = shown.map((l) => (l.ts ? `${l.ts} ${l.text}` : l.text)).join('\n')
    try {
      await navigator.clipboard.writeText(text)
      toast({ message: t('output.copied'), tone: 'ok' })
    } catch {
      toast({ message: t('output.copyFailed') })
    }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', padding: 'var(--sp-1) var(--sp-3)' }}>
        <div className="seg" role="group" aria-label={t('output.filter')}>
          {(['all', 'warn', 'error'] as const).map((f) => (
            <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {t(`output.level.${f}`)}
            </button>
          ))}
        </div>
        {follow ? null : (
          <button type="button" className="btn btn-sm" onClick={() => setFollow(true)}>
            <Icon spec={codicon('arrow-down')} />
            {t('output.jump')}
          </button>
        )}
        <button type="button" className="btn btn-sm" style={{ marginLeft: 'auto' }} onClick={() => void copy()} disabled={!shown.length}>
          <Icon spec={codicon('copy')} />
          {t('output.copy')}
        </button>
      </div>
      <div
        ref={list}
        role="log"
        aria-live="polite"
        className="mono"
        onScroll={onScroll}
        style={{ flex: 1, minHeight: 0, overflow: 'auto', fontSize: 'var(--fs-panel)', padding: '0 var(--sp-3) var(--sp-1)', whiteSpace: 'pre-wrap' }}
      >
        {shown.length ? (
          shown.map((l, i) => (
            <div key={i} style={{ color: color(l) }}>
              {l.ts ? <span className="muted">{l.ts} </span> : null}
              {l.text}
            </div>
          ))
        ) : (
          <div className="muted">{t('output.noLines')}</div>
        )}
      </div>
    </div>
  )
}
