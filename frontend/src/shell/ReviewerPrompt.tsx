import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Dialog } from '../lib'
import { resolveReviewerPrompt, useReviewer } from '../state'
import { codicon } from '../theme'

/** Asks for a reviewer name or initials on the first write (CUR-01). No accounts (ADR-0004). */
export function ReviewerPrompt() {
  const prompting = useReviewer((s) => s.prompting)
  return prompting ? <PromptDialog /> : null
}

function PromptDialog() {
  const { t } = useTranslation()
  const [name, setName] = useState(() => useReviewer.getState().name)
  const submit = () => name.trim() && resolveReviewerPrompt(name.trim())
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && resolveReviewerPrompt(null)}
      title={t('reviewer.title')}
      icon={codicon('account')}
      footer={
        <>
          <button type="button" className="btn" onClick={() => resolveReviewerPrompt(null)}>
            {t('common.cancel')}
          </button>
          <button type="button" className="btn btn-primary" disabled={!name.trim()} onClick={submit}>
            {t('reviewer.save')}
          </button>
        </>
      }
    >
      <form
        className="field"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <label className="field-label" htmlFor="reviewer-name">
          {t('reviewer.label')}
        </label>
        <input id="reviewer-name" className="input" value={name} autoFocus placeholder={t('reviewer.placeholder')} onChange={(e) => setName(e.target.value)} />
        <span className="muted" style={{ fontSize: 'var(--fs-panel)' }}>
          {t('reviewer.help')}
        </span>
      </form>
    </Dialog>
  )
}
