# ADR-0049 Timeline events are label table rows at an `event` level, dated in days from an anchor
Status: Accepted · Date: 2026-11-05 (owner decision) · Extends: ADR-0046 §6, ADR-0022
Does not supersede ADR-0046: it answers the question that ADR left open (event level, date policy).

**Context.** Survival and follow-up analysis needs dated events per patient (surgery, treatment, recurrence, death) next to the scan dates. Calendar dates are identifying (NFR-17); an event table also has several rows per case, which none of the label table levels (case, scan, item) allows.

**Decision.**
1. A label table may have level `event`: any number of rows per case, added and removed by the user. A row's target is `{case_id}#{n}` (n counts up per table, never reused). Row creation and removal are events in the `labeling` namespace (`kind: "row"`), so history, reviewer stamps, undo and live sync work as for cells (LBL-04, LBL-05).
2. An event table always has two columns: `kind` (category; the levels are the event types) and `day` (number, unit days). Other columns are optional. The server adds the two when a table is created without them.
3. **Date policy.** `day` counts days from the case's **anchor**, its earliest complete scan that has a date. The server stores and returns offsets only; no calendar date of an event is stored, and the Timeline response carries no calendar date either. A case with no dated scan has no anchor: its events keep their days, and the Timeline says the scans cannot be placed.
4. Event tables are not variables themselves. Per table and per level of `kind` they yield case-level variables `lbl.{table}.{kind}_days` (days to the first event of that kind, empty if none) and `lbl.{table}.{kind}_occurred` (yes/no, empty when the case has no event row at all), and per table `lbl.{table}.followup_days` (the last event's day). A time-to-event pair is `(kind_days if occurred else followup_days, occurred)`. These reach filters, colour-by and the Analysis panel through the existing variable path.
5. Cohort shows the **Timeline** of one case: scans and events on one day axis, a table alternative (DB-11), and a form that adds an event. The editing path is the label table's (ADR-0046 §2).

**Consequences.** One engine again; the label table tab edits event rows with the same editors. Event tables cost one more branch in `targets()` and in the variable layers. A censored time (no event) needs `followup_days`, which is only as good as the event rows the user entered.

**Rejected alternatives.** Storing event dates (identifying, and a second source of truth next to the scan dates). A separate events store (a second engine with the same cell semantics, rejected in ADR-0046). Computing the anchor per table (two tables could disagree on day 0).
