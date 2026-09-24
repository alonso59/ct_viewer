// VW-05: "CT (assumed) ▾" next to W/L, only when the visible item has no modality of its own.
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useTranslation } from 'react-i18next'

import { useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'
import { MODALITY_CHOICES } from './model/wl'

export function ModalityChip() {
  const { t } = useTranslation()
  const active = useViewerSync((s) => s.activeModality)
  const setModality = useViewerSync((s) => s.setModality)
  if (!active?.assumed) return null
  return (
    <Menu.Root>
      <Menu.Trigger className="toolbar-select" title={t('viewer.modality.help')} aria-label={t('viewer.modality.label')}>
        {t('viewer.modality.assumed', { modality: t(`viewer.modality.${active.value}`) })}
        <Icon spec={codicon('chevron-down')} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="overlay menu" sideOffset={4} align="start">
          {MODALITY_CHOICES.map((m) => (
            <Menu.Item key={m} className="menu-item" onSelect={() => setModality(active.key, m)}>
              <Icon spec={codicon(m === active.value ? 'check' : 'blank')} />
              {t(`viewer.modality.${m}`)}
            </Menu.Item>
          ))}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}
