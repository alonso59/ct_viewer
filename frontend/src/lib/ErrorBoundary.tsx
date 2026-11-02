// A render or effect failure stays inside its region: the rest of the window keeps working.
import { Component, type ReactNode } from 'react'

import i18n from '../i18n'
import { ProblemError } from '../api/problem'
import { ProblemCard } from './ProblemCard'

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    const problem = new ProblemError(0, 'render-failed', i18n.t('problemTitle.render-failed'), error.message, ['retry', 'reload'])
    return (
      <ProblemCard
        error={problem}
        onAction={{ retry: () => this.setState({ error: null }), reload: () => window.location.reload() }}
      />
    )
  }
}
