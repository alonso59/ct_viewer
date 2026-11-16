# ADR-0055 Phase selection is one drop-down, not one button per phase
Status: Accepted · Date: 2026-11-16
Supersedes: ADR-0026 §1 only for the shape of the header control (one button per `phase_vocabulary` value).

**Context.** ADR-0026 put one button per phase in the case/scan header. That fits a four-phase
vocabulary; a pack with more phases (the time-based `ct-phases` pack separates early and late
arterial phases) turns the header into a row of buttons, and the owner asked for a list instead.

**Decision.** The header shows one drop-down with the project's `phase_vocabulary`, each value as
code and name. Choosing a value is the same single write as before: an event at once, no
confirmation, Undo in the toast. "Accept guess", "was …", the history and the read-only Explorer
badges (ADR-0031) are unchanged.

**Consequences.** The header width no longer grows with the vocabulary. Setting a phase takes two
clicks instead of one; the keyboard commands per phase still exist.

**Rejected alternatives.** Buttons up to a size limit and a drop-down beyond it (two shapes of the
same control).
