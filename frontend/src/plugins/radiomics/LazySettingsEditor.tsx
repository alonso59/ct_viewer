// The settings form is its own chunk (FE-05, NFR-07)
import { lazy, Suspense } from 'react'
import { useTranslation } from 'react-i18next'

const Editor = lazy(() => import('./SettingsEditor').then((m) => ({ default: m.SettingsEditor })))

export function LazySettingsEditor() {
  const { t } = useTranslation()
  return (
    <Suspense fallback={<div className="empty">{t('common.loading')}</div>}>
      <Editor />
    </Suspense>
  )
}
