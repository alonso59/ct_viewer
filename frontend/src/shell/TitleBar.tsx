import * as Menu from '@radix-ui/react-dropdown-menu'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { IconButton } from '../lib'
import { useLayout } from '../state'
import { Icon, codicon } from '../theme'
import { bindingOf, commandTitle, formatChord, runCommand } from './keybindings'
import { MENUS, menuSections } from './menus'
import { registry, type Command, type MenuId } from './registry'
import { useWorkbench } from './workbenchStore'

function Item({ c }: { c: Command }) {
  const { t } = useTranslation()
  return (
    <Menu.Item className="menu-item" disabled={c.enabled ? !c.enabled() : false} onSelect={() => runCommand(c.id)}>
      {commandTitle(c, t)}
      <span className="kbd">{formatChord(bindingOf(c))}</span>
    </Menu.Item>
  )
}

/** One menu: a section per category (AUD-A1-09); views and panels open as submenus */
function MenuItems({ menu }: { menu: MenuId }) {
  const { t } = useTranslation()
  return (
    <>
      {menuSections(menu).map((s, i) => (
        <div key={s.category}>
          {i > 0 ? <Menu.Separator className="menu-sep" /> : null}
          {s.submenu ? (
            <Menu.Sub>
              <Menu.SubTrigger className="menu-item">
                {t(`menu.sub.${s.category.slice(4)}`)}
                <Icon spec={codicon('chevron-right')} />
              </Menu.SubTrigger>
              <Menu.Portal>
                <Menu.SubContent className="overlay menu" sideOffset={2}>
                  {s.commands.map((c) => <Item key={c.id} c={c} />)}
                </Menu.SubContent>
              </Menu.Portal>
            </Menu.Sub>
          ) : (
            s.commands.map((c, j) => (
              <div key={c.id}>
                {j > 0 && s.commands[j - 1]?.menuGroup !== c.menuGroup ? <Menu.Separator className="menu-sep" /> : null}
                <Item c={c} />
              </div>
            ))
          )}
        </div>
      ))}
    </>
  )
}

/** `share`: the project's share control (AUD-A1-11, from `features/projects`) */
export function TitleBar({ brand, share }: { brand: ReactNode; share?: ReactNode }) {
  const { t } = useTranslation()
  const layout = useLayout()
  const openPalette = useWorkbench((s) => s.openPalette)
  const quickOpen = registry.commands.get('workbench.quickOpen')
  return (
    <header className="titlebar">
      {brand}
      <nav className="titlebar-menus" aria-label={t('shell.menus')}>
        {MENUS.map(({ id: m }) => (
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
        {share}
        <IconButton icon={codicon('layout-sidebar-left')} label={t('cmd.toggleSidebar')} pressed={layout.sidebarVisible} onClick={() => layout.toggle('sidebarVisible')} />
        <IconButton icon={codicon('layout-panel')} label={t('cmd.togglePanel')} pressed={layout.panelVisible} onClick={() => layout.toggle('panelVisible')} />
        <IconButton icon={codicon('layout-sidebar-right')} label={t('cmd.toggleInspector')} pressed={layout.inspectorVisible} onClick={() => layout.toggle('inspectorVisible')} />
      </div>
    </header>
  )
}
