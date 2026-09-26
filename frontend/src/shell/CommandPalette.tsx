import { Command } from 'cmdk'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router'

import { bindingOf, commandTitle, formatChord } from './keybindings'
import { paletteScore } from './paletteMatch'
import { registry, routeScope } from './registry'
import { useWorkbench } from './workbenchStore'

/** Command palette (Ctrl/Cmd+Shift+P) and quick open (Ctrl/Cmd+P) on every route (UI-05,
 *  AUD-A1-01). A leading `>` switches to commands, as in VS Code. Only the commands of the
 *  current route are listed, ranked by `paletteScore` (AUD-A1-07). */
export function CommandPalette() {
  const { t } = useTranslation()
  const mode = useWorkbench((s) => s.palette)
  const openPalette = useWorkbench((s) => s.openPalette)
  const [value, setValue] = useState('')
  const open = mode !== null
  const commands = mode === 'commands' || value.startsWith('>')
  const query = commands ? value.replace(/^>\s*/, '') : value
  const close = () => {
    openPalette(null)
    setValue('')
  }
  // A palette never outlives its page (AUD-A2-09: a press on one route must not pop up on the next)
  const { pathname } = useLocation()
  const page = `${routeScope(pathname)}:${pathname.split('/')[2] ?? ''}`
  const lastPage = useRef(page)
  useEffect(() => {
    if (lastPage.current === page) return
    lastPage.current = page
    openPalette(null)
  }, [page, openPalette])
  const scope = routeScope(pathname)
  const cmds = commands ? [...registry.commands.values()].filter((c) => registry.available(c, scope) && (!c.enabled || c.enabled())) : []
  const byId = new Map(cmds.map((c) => [c.id, c]))
  return (
    <Command.Dialog
      open={open}
      onOpenChange={(o) => (o ? undefined : close())}
      label={t(commands ? 'palette.commands' : 'palette.quickOpen')}
      overlayClassName="dialog-scrim"
      contentClassName="overlay palette"
      shouldFilter={commands}
      filter={(id, search) => {
        const c = byId.get(id)
        return c ? paletteScore(search.replace(/^>\s*/, ''), commandTitle(c, t), (c.keywords ?? []).map((k) => t(k)), c.category ? t(c.category) : '') : 0
      }}
      loop
    >
      <Command.Input
        value={value}
        onValueChange={setValue}
        placeholder={t(commands ? 'palette.commandsPlaceholder' : scope === 'project' ? 'palette.quickOpenPlaceholder' : 'palette.quickOpenProjects')}
        autoFocus
      />
      <Command.List>
        <Command.Empty>{t('palette.empty')}</Command.Empty>
        {commands
          ? cmds.map((c) => (
              <Command.Item
                key={c.id}
                value={c.id}
                onSelect={() => {
                  close()
                  c.run()
                }}
              >
                {c.category ? <span className="palette-detail">{t('palette.category', { category: t(c.category) })}</span> : null}
                <span>{commandTitle(c, t)}</span>
                <span className="kbd palette-kbd">{formatChord(bindingOf(c))}</span>
              </Command.Item>
            ))
          : registry.quickOpen.filter((p) => (p.scope ?? ['project']).includes(scope)).map(({ id, component: C }) => <C key={id} query={query} close={close} />)}
      </Command.List>
    </Command.Dialog>
  )
}
