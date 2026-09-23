# ADR-0011 Study-agnostic variable catalog
Status: Accepted · Date: 2026-09-23

**Context.** v2 and the first v3 docs assumed a `group` column and kidney-specific labels. The real reference dataset has no `group`; its study labels are `hb`, `lb`, `sn` (case-level numeric percentages, half missing), next to ~150 DICOM/technical fields. Other datasets will carry different or no labels.

**Decision.** Only a minimal imaging core is hard-coded (case, scan, image, phase, masks, side). Every other field is a typed **variable** profiled on import (type, level, missing %), confirmed by the user, grouped as *Study* (unknown fields, visible) or *Acquisition* (known converter fields, hidden, confounder candidates). Three derived-variable operations (bin, recode, dominant) and an optional case-keyed external table cover grouping needs (VARIABLES.md). Label map and phase vocabulary become project presets (ccRCC preset = current defaults).

**Consequences.** + Works for any dataset without code changes; + study labels surface automatically. − Users must confirm ambiguous types (`sn`). − `group` disappears from items, case summaries and feature tables; filters and columns become variable-driven.

**Rejected.** Hard-coding `hb/lb/sn` or `group` (study-specific). A free expression language for derived variables (complexity).
