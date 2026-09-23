import { chordOf } from './keybindings'

const ev = (init: KeyboardEventInit & { code: string }) => new KeyboardEvent('keydown', init)

test('chords use physical keys so Shift+1 stays shift+1', () => {
  expect(chordOf(ev({ code: 'Digit1', key: '!', shiftKey: true }))).toBe('shift+1')
  expect(chordOf(ev({ code: 'KeyA', key: 'a' }))).toBe('a')
  expect(chordOf(ev({ code: 'ArrowDown', key: 'ArrowDown', altKey: true }))).toBe('alt+down')
  expect(chordOf(ev({ code: 'F8', key: 'F8' }))).toBe('f8')
})
