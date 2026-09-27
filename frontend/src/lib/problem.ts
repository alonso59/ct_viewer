// UI-18 / FE-09 (AUD-A6-12): the one problem → text helper. A problem reads as its cause
// (`detail`), else its title in plain words (`problemTitle.*`); its next steps (`actions[]`) are
// named with `problemAction.*`. Inline cards use ProblemCard; toasts and notes use these.
import i18n from '../i18n'
import { ProblemError, parseAction } from '../api/problem'

/** The cause of an error in words; `fallback` for anything that is not an API problem */
export function problemMessage(e: unknown, fallback?: string): string {
  if (e instanceof ProblemError) return e.detail ?? (e.generic ? i18n.t(`problemTitle.${e.type}`, { defaultValue: e.title }) : e.title)
  if (fallback !== undefined) return fallback
  return e instanceof Error && e.message ? e.message : i18n.t('common.error')
}

/** The problem's next steps in words (empty for other errors) */
export function problemActions(e: unknown): string[] {
  if (!(e instanceof ProblemError)) return []
  return e.actions.map((a) => {
    const { name, arg } = parseAction(a)
    return i18n.t(`problemAction.${name}`, { arg: arg ?? '', defaultValue: name })
  })
}

/** Toast text: the cause, then the next steps ("… Next: Choose the derived folder.") */
export function problemToastText(e: unknown, fallback?: string): string {
  const next = problemActions(e)
  const msg = problemMessage(e, fallback)
  return next.length ? i18n.t('problem.next', { message: msg, actions: next.join(' · ') }) : msg
}
