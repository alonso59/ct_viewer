// Left pane Curation view (QuPath Annotations analog): decision form, progress, queue shortcut
import { useTranslation } from 'react-i18next'

import { useCases, useQueue } from '../../api'
import { Progress } from '../../lib'
import { openEditor, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { CurationForm } from './CurationForm'
import '../../i18n/lazy'

export function CurationView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const cases = useCases(pid).data ?? []
  const queue = useQueue(pid).data ?? []
  const reviewed = cases.filter((c) => c.curation_status !== 'not_reviewed').length
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '0 12px 12px' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', fontSize: 'var(--fs-panel)' }}>
          <span>{t('curation.progress')}</span>
          <span className="muted num" style={{ marginLeft: 'auto' }}>{t('curation.progressCount', { done: reviewed, total: cases.length })}</span>
        </div>
        <Progress value={reviewed} total={cases.length} />
      </div>
      <CurationForm />
      <button type="button" className="btn btn-sm" onClick={() => openEditor('queue', {})}>
        <Icon spec={codicon('checklist')} />
        {t('curation.openQueue')}
        <span className="count" style={{ marginLeft: 'auto' }}>{queue.length}</span>
      </button>
    </div>
  )
}
