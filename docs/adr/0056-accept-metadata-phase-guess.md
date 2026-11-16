# ADR-0056 "Accept guess" also accepts the imported phase_guess
Status: Accepted · Date: 2026-11-16
Extends: ADR-0026 §3 (accepting a guess is a native phase event).

**Context.** A dataset prepared outside the app can carry a proposed phase per scan in the
`phase_guess` metadata field (INPUT_METADATA). The viewer shows it as the effective phase, but
"Accept guess" appeared only for the active `analyzer.phase` run, so a reviewer who agreed with an
imported proposal had no one-click way to confirm it, and the event history could not tell a
confirmed proposal from one nobody looked at.

**Decision.** When a scan's effective phase comes from `phase_guess`, the header shows "Accept
guess" too. It writes a phase event with `source: "guess_accept"` and no `accepted_run_id`. The
server accepts it only when the value equals that scan's `phase_guess`; other values must be
`manual` selections.

**Consequences.** Confirmed imported proposals are counted in the history and exports like any
selection. The import itself is unchanged and `phase_guess` keeps its place last in the precedence.

**Rejected alternatives.** Recording the confirmation as `manual` (loses the distinction between
agreeing with the proposal and choosing a phase); creating an analyzer run for imported guesses
(a run is a result of the app's own analyzers).
