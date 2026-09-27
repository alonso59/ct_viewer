// @vitest-environment jsdom
// UI-12 keybinding dispatch: chords, route scope (AUD-A1-01), viewer context without DOM focus
// (AUD-A2-02), typing, menus and modals (AUD-A2-09 / AUD-A1-17), view-only (UI-26). AUD-A6-04.
import { chordOf, dispatchKey } from './keybindings'
import { registry, routeScope, type Command } from './registry'
import { useWorkbench } from './workbenchStore'

const ev = (init: KeyboardEventInit & { code: string }) => new KeyboardEvent('keydown', init)

test('chords use physical keys so Shift+1 stays shift+1', () => {
  expect(chordOf(ev({ code: 'Digit1', key: '!', shiftKey: true }))).toBe('shift+1')
  expect(chordOf(ev({ code: 'KeyA', key: 'a' }))).toBe('a')
  expect(chordOf(ev({ code: 'ArrowDown', key: 'ArrowDown', altKey: true }))).toBe('alt+down')
  expect(chordOf(ev({ code: 'ArrowDown', key: 'ArrowDown', altKey: true, shiftKey: true }))).toBe('alt+shift+down')
  expect(chordOf(ev({ code: 'F8', key: 'F8' }))).toBe('f8')
})

test('route scope follows the pathname', () => {
  expect(routeScope('/')).toBe('home')
  expect(routeScope('/open/abc')).toBe('open')
  expect(routeScope('/open')).toBe('open')
  expect(routeScope('/opened')).toBe('home')
  expect(routeScope('/p/X/case/c1')).toBe('project')
  expect(routeScope('/v/tok')).toBe('project')
})

/** Press a key with `target` focused; true = a command ran */
function press(code: string, init: KeyboardEventInit = {}, target: HTMLElement = document.body): boolean {
  const e = new KeyboardEvent('keydown', { code, key: code.replace(/^Key/, '').toLowerCase(), bubbles: true, ...init })
  Object.defineProperty(e, 'target', { value: target })
  return dispatchKey(e)
}

describe('dispatch', () => {
  const ran: string[] = []
  const add = (c: Omit<Command, 'run'>) => registry.command({ ...c, run: () => ran.push(c.id) })
  let viewerShown = true

  beforeAll(() => {
    add({ id: 't.accept', title: 't', keybinding: 'a', when: 'viewer', writes: true })
    add({ id: 't.next', title: 't', keybinding: 'alt+down' })
    add({ id: 't.palette', title: 't', keybinding: 'mod+shift+k', scope: ['home', 'open', 'project'] })
    add({ id: 't.homeOnly', title: 't', keybinding: 'n', scope: ['home'] })
    add({ id: 't.off', title: 't', keybinding: 'o', enabled: () => false })
    registry.context('viewer', () => viewerShown)
  })
  afterAll(() => {
    for (const id of ['t.accept', 't.next', 't.palette', 't.homeOnly', 't.off']) registry.commands.delete(id)
    registry.contexts.delete('viewer')
    history.replaceState(null, '', '/')
  })
  beforeEach(() => {
    ran.length = 0
    viewerShown = true
    registry.setReadOnly(false)
    history.replaceState(null, '', '/p/PID/case/c1')
    document.body.innerHTML = ''
    useWorkbench.setState({ pid: 'PID' })
  })

  test('viewer keys need a shown viewer, not DOM focus in it: A → Alt+↓ → A records both (AUD-A2-02)', () => {
    expect(press('KeyA')).toBe(true)
    expect(press('ArrowDown', { altKey: true })).toBe(true)
    // focus is nowhere after the tab change; the second A still reaches the new case
    expect(press('KeyA')).toBe(true)
    expect(ran).toEqual(['t.accept', 't.next', 't.accept'])
    // focus in the Explorer tree: still the viewer context
    const tree = document.createElement('div')
    tree.setAttribute('role', 'tree')
    document.body.append(tree)
    expect(press('KeyA', {}, tree)).toBe(true)
    viewerShown = false
    expect(press('KeyA')).toBe(false)
  })

  test('plain keys never fire while typing; modifier chords do', () => {
    const input = document.createElement('input')
    document.body.append(input)
    expect(press('KeyA', {}, input)).toBe(false)
    expect(press('ArrowDown', { altKey: true }, input)).toBe(true)
    expect(ran).toEqual(['t.next'])
  })

  test('nothing global while a modal is open or a menu has focus (AUD-A2-09, AUD-A1-17)', () => {
    const dialog = document.createElement('div')
    dialog.setAttribute('role', 'dialog')
    dialog.dataset.state = 'open'
    document.body.append(dialog)
    expect(press('KeyK', { ctrlKey: true, shiftKey: true })).toBe(false)
    expect(press('KeyA')).toBe(false)
    dialog.remove()
    const menu = document.createElement('div')
    menu.setAttribute('role', 'menu')
    const item = document.createElement('div')
    menu.append(item)
    document.body.append(menu)
    expect(press('KeyA', {}, item)).toBe(false)
    expect(ran).toEqual([])
  })

  test('only the commands of the current route fire (AUD-A1-01)', () => {
    expect(press('KeyN')).toBe(false)
    history.replaceState(null, '', '/')
    expect(press('KeyN')).toBe(true)
    expect(press('ArrowDown', { altKey: true })).toBe(false)
    expect(press('KeyK', { ctrlKey: true, shiftKey: true })).toBe(true)
    history.replaceState(null, '', '/open/s1')
    expect(press('KeyK', { ctrlKey: true, shiftKey: true })).toBe(true)
    expect(ran).toEqual(['t.homeOnly', 't.palette', 't.palette'])
  })

  test('disabled and view-only-hidden commands do not fire (UI-26)', () => {
    expect(press('KeyO')).toBe(false)
    registry.setReadOnly(true)
    expect(press('KeyA')).toBe(false)
    expect(press('ArrowDown', { altKey: true })).toBe(true)
    registry.setReadOnly(false)
    expect(ran).toEqual(['t.next'])
  })

  test('key repeat only repeats Alt chords (holding Alt+↓ walks the cases)', () => {
    expect(press('KeyA', { repeat: true })).toBe(false)
    expect(press('ArrowDown', { altKey: true, repeat: true })).toBe(true)
  })
})
