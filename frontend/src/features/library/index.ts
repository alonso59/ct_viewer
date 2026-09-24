// Plugin Library view (UI-22): core, lazy with its strings (NFR-07).
import { createElement, lazy, Suspense } from 'react'

import { registry } from '../../shell'
import { codicon } from '../../theme'

const View = lazy(() => Promise.all([import('./LibraryView'), import('../../i18n/lazy')]).then(([m]) => m))

function LazyView() {
  return createElement(Suspense, { fallback: null }, createElement(View))
}

export function registerLibrary() {
  registry.view({ id: 'library', title: 'view.library', icon: codicon('extensions'), order: 90, component: LazyView, hideImageSection: true })
}
