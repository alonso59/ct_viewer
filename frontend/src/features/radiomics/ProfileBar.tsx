// Profiles (RAD-03): save, load, rename, duplicate, delete. A profile is identified by the hash of
// its settings, so saving settings that already have a profile returns that profile.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDeleteProfile, useProfiles, useRenameProfile, useSaveProfile } from '../../api'
import { Dialog, IconButton, fmtAgo } from '../../lib'
import { toast } from '../../shell'
import { Icon, codicon } from '../../theme'
import { errorMessage } from './errors'
import { fromWire } from './model/settings'
import type { Profile, SettingsSchema, WireSettings } from './model/types'
import { useDraft } from './store'

const shortHash = (h: string) => h.replace(/^sha256:/, '').slice(0, 8)

export function ProfileBar({ pid, schema, wire }: { pid: string; schema: SettingsSchema; wire: WireSettings | null }) {
  const { t } = useTranslation()
  const profiles = useProfiles(pid)
  const save = useSaveProfile(pid)
  const rename = useRenameProfile(pid)
  const del = useDeleteProfile(pid)
  const setForm = useDraft((s) => s.setForm)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [editing, setEditing] = useState<{ hash: string; name: string } | null>(null)
  const list = profiles.data ?? []

  const load = (p: Profile) => {
    setForm(fromWire(schema, p.settings), p.name)
    toast({ message: t('rad.profileLoaded', { name: p.name }), tone: 'info' })
  }
  const doSave = async () => {
    if (!wire || !name.trim()) return
    const before = new Set(list.map((p) => p.profile_hash))
    try {
      const p = await save.mutateAsync({ name: name.trim(), settings: wire })
      const existed = before.has(p.profile_hash)
      toast({ message: existed ? t('rad.profileExists', { name: p.name }) : t('rad.profileSaved', { name: p.name, hash: shortHash(p.profile_hash) }), tone: existed ? 'info' : 'ok' })
      useDraft.setState({ loadedFrom: p.name })
      setName('')
    } catch (e) {
      toast({ message: errorMessage(e, t('common.saveFailed')), tone: 'error' })
    }
  }
  const doRename = async () => {
    if (!editing?.name.trim()) return
    try {
      await rename.mutateAsync({ hash: editing.hash, name: editing.name.trim() })
      setEditing(null)
    } catch (e) {
      toast({ message: errorMessage(e, t('common.saveFailed')), tone: 'error' })
    }
  }
  const doDelete = async (p: Profile) => {
    try {
      await del.mutateAsync(p.profile_hash)
      toast({ message: t('rad.profileDeleted', { name: p.name }), tone: 'info' })
    } catch (e) {
      toast({ message: errorMessage(e, t('common.saveFailed')), tone: 'error' })
    }
  }

  return (
    <>
      <select
        className="select input-sm"
        aria-label={t('rad.loadProfile')}
        value=""
        onChange={(e) => {
          const p = list.find((x) => x.profile_hash === e.target.value)
          if (p) load(p)
        }}
      >
        <option value="">{t('rad.loadProfile')}</option>
        {list.map((p) => (
          <option key={p.profile_hash} value={p.profile_hash}>{t('rad.profileOption', { name: p.name, hash: shortHash(p.profile_hash) })}</option>
        ))}
      </select>
      <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>
        <Icon spec={codicon('symbol-namespace')} />
        {t('rad.profiles')}
      </button>
      <Dialog open={open} onOpenChange={setOpen} title={t('rad.profiles')} icon={codicon('symbol-namespace')} size="lg">
        <div className="rad-profile-save">
          <label className="field" style={{ flex: 1 }}>
            <span className="field-label">{t('rad.saveCurrentAs')}</span>
            <input
              className="input input-sm"
              value={name}
              placeholder={t('rad.profileName')}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void doSave()
              }}
            />
          </label>
          <button type="button" className="btn btn-sm btn-primary" disabled={!name.trim() || !wire || save.isPending} onClick={() => void doSave()}>
            <Icon spec={codicon('save')} />
            {t('common.save')}
          </button>
        </div>
        <span className="muted rad-help">{t('rad.profileHashHelp')}</span>
        {profiles.isLoading ? <div className="muted">{t('common.loading')}</div> : null}
        {profiles.error ? <div className="field-error">{errorMessage(profiles.error, t('common.error'))}</div> : null}
        {!profiles.isLoading && list.length === 0 ? <div className="muted">{t('rad.noProfiles')}</div> : null}
        <ul className="rad-profile-list">
          {list.map((p) => (
            <li key={p.profile_hash} className="rad-profile">
              {editing?.hash === p.profile_hash ? (
                <input
                  className="input input-sm"
                  aria-label={t('rad.rename')}
                  autoFocus
                  value={editing.name}
                  onChange={(e) => setEditing({ hash: p.profile_hash, name: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void doRename()
                    if (e.key === 'Escape') setEditing(null)
                  }}
                />
              ) : (
                <span className="rad-profile-name">
                  <strong>{p.name}</strong>
                  <span className="muted mono">{shortHash(p.profile_hash)}</span>
                  <span className="muted">{t('rad.profileMeta', { engine: `${p.engine.name} ${p.engine.major}`, ago: fmtAgo(p.updated_at) })}</span>
                </span>
              )}
              <span className="rad-profile-actions">
                {editing?.hash === p.profile_hash ? (
                  <IconButton label={t('common.save')} icon={codicon('check')} onClick={() => void doRename()} />
                ) : (
                  <>
                    <IconButton
                      label={t('rad.load')}
                      icon={codicon('folder-opened')}
                      onClick={() => {
                        load(p)
                        setOpen(false)
                      }}
                    />
                    <IconButton label={t('rad.rename')} icon={codicon('edit')} onClick={() => setEditing({ hash: p.profile_hash, name: p.name })} />
                    <IconButton
                      label={t('rad.duplicate')}
                      icon={codicon('copy')}
                      onClick={() => {
                        load(p)
                        setName(t('rad.copyOf', { name: p.name }))
                      }}
                    />
                    <IconButton label={t('rad.delete')} icon={codicon('trash')} onClick={() => void doDelete(p)} />
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      </Dialog>
    </>
  )
}
