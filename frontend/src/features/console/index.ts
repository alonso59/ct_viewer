import { Suspense, createElement, lazy } from 'react'

import { registry } from '../../shell'

// The console and its strings stay out of the initial bundle (NFR-07)
const ConsoleLazy = lazy(() => import('./ConsolePanel').then((m) => ({ default: m.ConsolePanel })))
const ConsolePanel = () => createElement(Suspense, { fallback: null }, createElement(ConsoleLazy))

export function registerConsole() {
  // it starts runs: hidden on view-only links (UI-26)
  registry.panelTab({ id: 'console', title: 'panel.console', order: 45, component: ConsolePanel, writes: true })
}
