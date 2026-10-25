// The `/open` route's contract, shared by every feature that opens a path (in lib/ so the import
// wizard and the converter need not import the Open-mode feature).
// The Open-mode URL names the session (`/open/{sid}`), never the path.
// A path to open travels in the history entry's state; OpenRoute opens it and replaces
// the entry with `/open/{sid}`, so the path is neither in the address bar nor in copied links.
import type { NavigateFunction } from 'react-router'

type OpenState = { openPath: string }

export const openPath = (navigate: NavigateFunction, path: string) => navigate('/open', { state: { openPath: path } satisfies OpenState })

export const pendingPath = (state: unknown): string | null => {
  const p = (state as Partial<OpenState> | null)?.openPath
  return typeof p === 'string' && p ? p : null
}
