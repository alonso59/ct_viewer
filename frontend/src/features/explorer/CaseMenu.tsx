import * as Menu from '@radix-ui/react-dropdown-menu'
import { useTranslation } from 'react-i18next'
import { create } from 'zustand'

import { runCommand } from '../../shell'
import { Icon, codicon } from '../../theme'

interface CaseMenuState {
  caseId: string | null
  x: number
  y: number
  open: (caseId: string, x: number, y: number) => void
  close: () => void
}

export const useCaseMenu = create<CaseMenuState>()((set) => ({
  caseId: null,
  x: 0,
  y: 0,
  open: (caseId, x, y) => set({ caseId, x, y }),
  close: () => set({ caseId: null }),
}))

/** A right-clicked case row: the case's actions that leave the Explorer */
export function CaseMenu() {
  const { t } = useTranslation()
  const caseId = useCaseMenu((s) => s.caseId)
  const x = useCaseMenu((s) => s.x)
  const y = useCaseMenu((s) => s.y)
  const close = useCaseMenu((s) => s.close)
  if (!caseId) return null
  return (
    <Menu.Root open onOpenChange={(o) => !o && close()} modal={false}>
      <Menu.Trigger asChild>
        <span aria-hidden style={{ position: 'fixed', left: x, top: y, width: 1, height: 1 }} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="overlay menu" align="start" sideOffset={2}>
          <Menu.Label className="menu-label">{caseId}</Menu.Label>
          <Menu.Item className="menu-item" onSelect={() => runCommand('cohort.showCase', caseId)}>
            <Icon spec={codicon('table')} />
            {t('explorer.showInCohort')}
          </Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}
