import { useVirtualizer } from '@tanstack/react-virtual'
import { useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { LogLine } from '../../api'
import { ProblemCard } from '../../lib'
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

const lineText = (l: LogLine) => (l.ts ? `${l.ts} ${l.text}` : l.text)

/** The one log view of every Output channel: a terminal-like, virtualised list that follows new
 *  lines until the user scrolls up, with level and text filters; Copy and Download act on the
 *  lines shown. Download is a file made in the browser, no request. */
export function LogView({ lines, first = 0, name, empty, loading = false, error, onRetry, ended = false, redacted = false }: {
  lines: LogLine[]
  /** Sequence number of `lines[0]` (older lines were dropped): rows keep their keys */
  first?: number
  /** Download's file name, without `.log` */
  name: string
  /** Shown while the channel has no line yet */
  empty?: string
  loading?: boolean
  error?: unknown
  onRetry?: () => void
  /** The source finished: no line will follow */
  ended?: boolean
  /** A server log: host paths are replaced by data-root names */
  redacted?: boolean
}) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [follow, setFollow] = useState(true)
  const list = useRef<HTMLDivElement>(null)
  const needle = query.trim().toLowerCase()
  const shown = lines.flatMap((line, i) =>
    SHOWN[filter].has(line.level) && (!needle || lineText(line).toLowerCase().includes(needle)) ? [{ line, seq: first + i }] : [],
  )
  // TanStack Virtual is not React-compiler compatible yet; the compiler skips this component, which is fine here
  // eslint-disable-next-line react-hooks/incompatible-library
  const virt = useVirtualizer({
    count: shown.length,
    getScrollElement: () => list.current,
    estimateSize: () => 18,
    getItemKey: (i) => shown[i]?.seq ?? i,
    overscan: 20,
  })
  const height = virt.getTotalSize()
  // measured rows change the height: stay pinned to the end while following
  useLayoutEffect(() => {
    const el = list.current
    if (follow && el) el.scrollTop = el.scrollHeight
  }, [follow, shown.length, lines, height])
  const onScroll = () => {
    const el = list.current
    if (el) setFollow(el.scrollTop + el.clientHeight >= el.scrollHeight - 4)
  }
  const text = () => shown.map((s) => lineText(s.line)).join('\n')
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text())
      toast({ message: shown.length < lines.length ? t('output.copiedSome', { n: shown.length, total: lines.length }) : t('output.copiedAll', { count: shown.length }), tone: 'ok' })
    } catch {
      toast({ message: t('output.copyFailed') })
    }
  }
  const download = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([`${text()}\n`], { type: 'text/plain' }))
    a.download = `${name.replace(/[^\w.-]+/g, '_')}.log`
    a.click()
    URL.revokeObjectURL(a.href)
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)', padding: 'var(--sp-1) var(--sp-3)' }}>
        <div className="seg" role="group" aria-label={t('output.filter')}>
          {(['all', 'warn', 'error'] as const).map((f) => (
            <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {t(`output.level.${f}`)}
            </button>
          ))}
        </div>
        <input className="input input-sm" type="search" value={query} aria-label={t('output.search')} placeholder={t('output.search')} onChange={(e) => setQuery(e.target.value)} />
        {follow ? null : (
          <button type="button" className="btn btn-sm" onClick={() => setFollow(true)}>
            <Icon spec={codicon('arrow-down')} />
            {t('output.jump')}
          </button>
        )}
        <span style={{ flex: 1 }} />
        {redacted ? <span className="muted" title={t('output.redactedHelp')}>{t('output.redacted')}</span> : null}
        <button type="button" className="btn btn-sm" onClick={() => void copy()} disabled={!shown.length}>
          <Icon spec={codicon('copy')} />
          {t('output.copy')}
        </button>
        <button type="button" className="btn btn-sm" title={t('output.downloadHelp')} onClick={download} disabled={!shown.length}>
          <Icon spec={codicon('desktop-download')} />
          {t('output.download')}
        </button>
      </div>
      {error ? <ProblemCard error={error} onRetry={onRetry} /> : null}
      <div
        ref={list}
        role="log"
        aria-live="polite"
        className="mono"
        onScroll={onScroll}
        style={{ flex: 1, minHeight: 0, overflow: 'auto', fontSize: 'var(--fs-panel)', padding: '0 var(--sp-3) var(--sp-1)', whiteSpace: 'pre-wrap' }}
      >
        {shown.length ? (
          <div style={{ position: 'relative', height }}>
            {virt.getVirtualItems().map((v) => {
              const l = shown[v.index]!.line
              return (
                <div key={v.key} data-index={v.index} ref={virt.measureElement} style={{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${v.start}px)`, color: color(l) }}>
                  {l.ts ? <span className="muted">{l.ts} </span> : null}
                  {l.text}
                </div>
              )
            })}
          </div>
        ) : (
          <div className="muted">{loading ? t('common.loading') : lines.length ? t('output.noMatch') : (empty ?? t('output.noLines'))}</div>
        )}
        {ended ? <div className="muted">{t('output.ended')}</div> : null}
      </div>
    </div>
  )
}
