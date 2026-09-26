// Quick open (Ctrl/Cmd+P): jump to a case or an item (UI-05)
import { Command } from 'cmdk'
import { useTranslation } from 'react-i18next'

import { useCases } from '../../api'
import { PhaseChip, StatusIcon } from '../../lib'
import { useWorkbench } from '../../shell'
import { openFromExplorer } from './navigate'

export function QuickOpenCases({ query, close }: { query: string; close: () => void }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data } = useCases(pid, { showExcluded: true })
  const q = query.trim().toLowerCase().replace(/^case_?/, '')
  const list = (data ?? []).filter((c) => !q || c.case_id.includes(q) || (c.patient_id ?? '').toLowerCase().includes(q)).slice(0, 50)
  return (
    <Command.Group heading={t('palette.cases')}>
      {list.map((c) => (
        <Command.Item
          key={c.case_id}
          value={c.case_id}
          onSelect={() => {
            close()
            openFromExplorer(c.case_id, null, false)
          }}
        >
          <StatusIcon status={c.curation_status} />
          <span className="mono">{c.case_id}</span>
          <span className="palette-detail">{c.patient_id}</span>
          <span style={{ display: 'inline-flex', gap: 4, marginLeft: 'auto' }}>
            {c.phases.map((p) => (
              <PhaseChip key={p} phase={p} />
            ))}
          </span>
        </Command.Item>
      ))}
    </Command.Group>
  )
}
