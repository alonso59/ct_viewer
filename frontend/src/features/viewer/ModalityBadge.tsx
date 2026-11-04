// The visible item's modality next to W/L: its DICOM code ("CT", "MR · Phase"), or, when the item
// has none, the assumed one with a menu to change it.
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useTranslation } from 'react-i18next'

import { MODALITY_CHOICES, ModalityTag, modalityText } from '../../lib'
import { useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'

export function ModalityBadge() {
  const { t } = useTranslation()
  const active = useViewerSync((s) => s.activeModality)
  const setModality = useViewerSync((s) => s.setModality)
  if (!active) return null
  if (!active.assumed) return <ModalityTag label={modalityText(t, active.value, active.component)} />
  const text = t('viewer.modality.assumed', { modality: modalityText(t, active.value) })
  return (
    <Menu.Root>
      <Menu.Trigger className="badge" data-tone="warn" title={t('viewer.modality.help')} aria-label={t('viewer.modality.named', { value: text })}>
        {text}
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
