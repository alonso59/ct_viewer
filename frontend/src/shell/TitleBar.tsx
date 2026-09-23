import * as Menu from '@radix-ui/react-dropdown-menu'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { IconButton } from '../lib'
import { useLayout } from '../state'
import { Icon, codicon } from '../theme'
import { bindingOf, formatChord, runCommand } from './keybindings'
import { registry, type MenuId } from './registry'
import { toast, useWorkbench } from './workbenchStore'

const MENUS: MenuId[] = ['file', 'edit', 'view', 'project', 'radiomics', 'help']

function MenuItems({ menu }: { menu: MenuId }) {
  const { t } = useTranslation()
  const cmds = [...registry.commands.values()]
    .filter((c) => c.menu === menu)
    .sort((a, b) => (a.menuGroup ?? 0) - (b.menuGroup ?? 0))
  return (
    <>
      {cmds.map((c, i) => {
        const prev = cmds[i - 1]
        return (
          <div key={c.id}>
            {prev && prev.menuGroup !== c.menuGroup ? <Menu.Separator className="menu-sep" /> : null}
            <Menu.Item className="menu-item" disabled={c.enabled ? !c.enabled() : false} onSelect={() => runCommand(c.id)}>
              {t(c.title)}
              <span className="kbd">{formatChord(bindingOf(c))}</span>
            </Menu.Item>
          </div>
        )
      })}
    </>
  )
}

export function TitleBar({ brand, shareUrl }: { brand: ReactNode; shareUrl?: string }) {
  const { t } = useTranslation()
  const layout = useLayout()
  const openPalette = useWorkbench((s) => s.openPalette)
  const quickOpen = registry.commands.get('workbench.quickOpen')
  return (
    <header className="titlebar">
      {brand}
      <nav className="titlebar-menus" aria-label={t('shell.menus')}>
        {MENUS.map((m) => (
          <Menu.Root key={m}>
            <Menu.Trigger className="titlebar-menu">{t(`menu.${m}`)}</Menu.Trigger>
            <Menu.Portal>
              <Menu.Content className="overlay menu" align="start" sideOffset={2}>
                <MenuItems menu={m} />
              </Menu.Content>
            </Menu.Portal>
          </Menu.Root>
        ))}
      </nav>
      <button type="button" className="titlebar-search" onClick={() => openPalette('quickopen')}>
        <Icon spec={codicon('search')} />
        <span>{t('shell.goToCase')}</span>
        <span className="kbd">{quickOpen ? formatChord(bindingOf(quickOpen)) : null}</span>
      </button>
      <div className="titlebar-right">
        {shareUrl ? (
          <IconButton
            icon={codicon('link')}
            label={t('shell.copyShareLink')}
            onClick={() => {
              void navigator.clipboard?.writeText(shareUrl)
              toast({ message: t('shell.shareLinkCopied'), tone: 'ok' })
            }}
          />
        ) : null}
        <IconButton icon={codicon('layout-sidebar-left')} label={t('cmd.toggleSidebar')} pressed={layout.sidebarVisible} onClick={() => layout.toggle('sidebarVisible')} />
        <IconButton icon={codicon('layout-panel')} label={t('cmd.togglePanel')} pressed={layout.panelVisible} onClick={() => layout.toggle('panelVisible')} />
        <IconButton icon={codicon('layout-sidebar-right')} label={t('cmd.toggleInspector')} pressed={layout.inspectorVisible} onClick={() => layout.toggle('inspectorVisible')} />
      </div>
    </header>
  )
}
