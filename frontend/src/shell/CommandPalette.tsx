import { Command } from 'cmdk'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { bindingOf, formatChord } from './keybindings'
import { registry } from './registry'
import { useWorkbench } from './workbenchStore'

/** Command palette (Ctrl/Cmd+Shift+P) and quick open (Ctrl/Cmd+P). A leading `>` switches to commands, as in VS Code (UI-05). */
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
  return (
    <Command.Dialog
      open={open}
      onOpenChange={(o) => (o ? undefined : close())}
      label={t(commands ? 'palette.commands' : 'palette.quickOpen')}
      overlayClassName="dialog-scrim"
      contentClassName="overlay palette"
      shouldFilter={commands}
      loop
    >
      <Command.Input
        value={value}
        onValueChange={setValue}
        placeholder={t(commands ? 'palette.commandsPlaceholder' : 'palette.quickOpenPlaceholder')}
        autoFocus
      />
      <Command.List>
        <Command.Empty>{t('palette.empty')}</Command.Empty>
        {commands
          ? [...registry.commands.values()].filter((c) => registry.allowed(c))
              .filter((c) => !c.enabled || c.enabled())
              .map((c) => (
                <Command.Item
                  key={c.id}
                  value={`${c.category ? t(c.category) : ''} ${t(c.title)} ${c.id}`}
                  onSelect={() => {
                    close()
                    c.run()
                  }}
                >
                  {c.category ? <span className="palette-detail">{t('palette.category', { category: t(c.category) })}</span> : null}
                  <span>{t(c.title)}</span>
                  <span className="kbd palette-kbd">{formatChord(bindingOf(c))}</span>
                </Command.Item>
              ))
          : registry.quickOpen.map(({ id, component: C }) => <C key={id} query={query} close={close} />)}
      </Command.List>
    </Command.Dialog>
  )
}
