// Message for a validation issue: client issues are translated by key, server issues carry `msg`.
import { useTranslation } from 'react-i18next'

import type { Issue } from './model/types'

export function useIssueMessage() {
  const { t } = useTranslation()
  return (i: Issue): string => (i.key ? t(`rad.rule.${i.key}`, i.params ?? {}) : (i.msg ?? i.rule))
}

export function IssueText({ issue, className }: { issue: Issue; className?: string }) {
  const msg = useIssueMessage()
  return <span className={className}>{msg(issue)}</span>
}
