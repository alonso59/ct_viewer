# ADR-0031 Explorer phases are read-only indicators
Status: Accepted · Date: 2026-10-21
Supersedes: ADR-0026 §1 only for phase-editing controls in Explorer rows.

**Context.** The owner wants the left case/scan panel to show phases without
allowing phase changes while navigating. Hovering or selecting a row previously
replaced the static phase badge with editing buttons.

**Decision.** PHS-01 owns the revised interaction and indicator colors. Explorer
case and scan/item rows always show read-only phase badges. Phase editing remains
in the viewer header and existing phase commands. The effective-phase layer,
history, exports and synchronization from ADR-0026 are unchanged.

**Consequences.** Navigation cannot accidentally change a scan's phase. Hover,
keyboard focus and selected rows retain the same phase indicator.

**Rejected alternatives.** Disabled phase buttons (still look editable), or
hover-only editing controls (retain the accidental-edit interaction).
