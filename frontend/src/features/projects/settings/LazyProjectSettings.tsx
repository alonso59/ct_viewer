// The settings tab and its strings load on first open (NFR-07).
import { lazy } from 'react'

import type { EditorProps } from '../../../shell'
import type { SettingsParams } from './ProjectSettings'

const Settings = lazy(() => Promise.all([import('./ProjectSettings'), import('../../../i18n/lazy')]).then(([m]) => m))

export function LazyProjectSettings(props: EditorProps<SettingsParams>) {
  return <Settings {...props} />
}
