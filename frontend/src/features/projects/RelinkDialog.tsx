// Relink dialog (PRJ-05, API-05), shared by the workspace home and the bundle import report; its
// own module so neither imports the other (AUD-A6-10).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useRelink, useRoots, type RelinkResult } from '../../api'
import { Dialog } from '../../lib'
import { toast } from '../../shell'
import { codicon } from '../../theme'

/** Relink (PRJ-05, API-05): point an alias at a new root; the server verifies a sample of items */
export function RelinkDialog({ pid, name, onOpenChange }: { pid: string; name: string; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const roots = useRoots(pid)
  const relink = useRelink(pid)
  const [alias, setAlias] = useState<string | null>(null)
  const [path, setPath] = useState('')
  const [result, setResult] = useState<RelinkResult | null>(null)
  const root = roots.data?.find((r) => r.alias === alias) ?? roots.data?.find((r) => !r.exists) ?? roots.data?.[0]
  const ok = result !== null && result.root.exists && result.verify.mismatched === 0 && result.verify.missing === 0
  const verify = async () => {
    if (!root) return
    const r = await relink.mutateAsync({ alias: root.alias, path: path.trim() })
    setResult(r)
    if (r.root.exists && r.verify.mismatched === 0 && r.verify.missing === 0) {
      void roots.refetch()
      toast({ message: t('projects.relinked', { alias: root.alias }), tone: 'ok' })
    }
  }
  return (
    <Dialog
      open
      onOpenChange={onOpenChange}
      title={t('projects.relinkTitle', { name })}
      icon={codicon('link')}
      footer={
        <>
          <button type="button" className="btn" onClick={() => onOpenChange(false)}>{t(ok ? 'common.close' : 'common.cancel')}</button>
          {!ok ? (
            <button type="button" className="btn btn-primary" disabled={!path.trim() || !root || relink.isPending} onClick={() => void verify()}>
              {relink.isPending ? t('projects.verifying') : t('projects.verify')}
            </button>
          ) : null}
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div className="muted panel-size">{t('projects.relinkHelp')}</div>
        {roots.data && roots.data.length > 1 ? (
          <label className="field">
            <span className="field-label">{t('projects.alias')}</span>
            <select className="select" value={root?.alias ?? ''} onChange={(e) => { setAlias(e.target.value); setResult(null) }}>
              {roots.data.map((r) => (
                <option key={r.alias} value={r.alias}>{r.alias}</option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="props" style={{ padding: 0 }}>
          <span className="muted">{t('projects.alias')}</span>
          <span className="mono">{root?.alias ?? '—'}</span>
          <span className="muted">{t('projects.oldPath')}</span>
          <span className="mono">
            {root?.path ?? '—'}
            {root && !root.exists ? <span className="badge" data-tone="error" style={{ marginLeft: 6 }}>{t('projects.offline')}</span> : null}
          </span>
        </div>
        <label className="field">
          <span className="field-label">{t('projects.newPath')}</span>
          <input className="input mono" value={path} placeholder={root?.path ?? t('projects.newPathPlaceholder')} onChange={(e) => { setPath(e.target.value); setResult(null) }} />
        </label>
        {relink.isError ? <div className="error-card" style={{ margin: 0 }}>{relink.error.message}</div> : null}
        {result ? (
          <div className={ok ? 'card' : 'error-card'} style={{ margin: 0 }} role="status">
            {t(ok ? 'projects.verifyOk' : 'projects.verifyFailed', {
              sampled: result.verify.sampled,
              matched: result.verify.matched,
              mismatched: result.verify.mismatched,
              missing: result.verify.missing,
            })}
          </div>
        ) : null}
      </div>
    </Dialog>
  )
}

/** Axial thumbnail of the project's first case (Open Recent) */
