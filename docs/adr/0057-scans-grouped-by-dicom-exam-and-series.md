# ADR-0057 Scans are grouped by DICOM exam and series, for display only
Status: Accepted · Date: 2026-11-17
Extends: ADR-0011 (a display grouping from converter facts, not a core entity). Amends: VW-11, UI-08, UI-13.

**Context.** The Explorer and the scan switcher list a case's scans flat by `scan_idx`, which breaks down on real cohorts:
- CT batch `b01-1`: a median of 4 exams and 18 CT volumes per patient (up to 16 and 81).
- MR sample: a median of 22 volumes over 2 exams; DCM-35 parts (`#t2`, `#b800`, `#e2`) of one dynamic get scattered indices (155, 203, 204, 205).
- `series_description` is empty for 78 % of those CT and 71 % of those MR volumes, so a switcher entry shows little more than a number.

Users want an acquisition unit (dynamic + its ADC, no subtractions), but that is study logic (ADR-0011, ADR-0020). Every converted row already carries `study_uid`, `series_uid`, `series_number` and `days_from_first_scan`.

**Decision.**
1. **Hierarchy** inside a case: **exam** = `study_uid` → **series** = `series_uid` without the DCM-35 `#…` suffix → **part** = the suffix (the first part has none).
2. **Order.** Exams by `days_from_first_scan` (missing last), then their lowest `scan_idx`. Series by numeric `series_number` (missing last), then their lowest `scan_idx`. Parts: the unsuffixed one first, then by `scan_idx`.
3. **No single-child levels.** The exam level is omitted when the case has one exam; the series level when a series has one part (every CT series). A case without `study_uid` stays flat; scans without one go last, under "Other scans".
4. **Labels never show identifiers or dates.** Exam: "Exam · day N" (offset as in ADR-0049, NFR-17), with an ordinal for two exams on the same day, or "Exam N" (its position) without an offset. Series: "Series {series_number}", plus its description when it has one. Scan: its part label (`t2`, `b800`, `e2`) and effective phase. UIDs appear only in tooltips (UI-08).
5. **Where.**
   - Explorer (UI-08): collapsible group rows (open by default), → / ← to expand and collapse, folded rows kept per project (UI-13).
   - Scan switcher (VW-11): sectioned menu; previous / next and "n of N" follow the grouped order, so TP1 → TP4 and b0 → ADC are adjacent steps.
   - The phase filter hides a group with no matching scan.
6. **Display only**, from those four converter fields. Nothing is stored; no `item_id`, index or API changes. Variables, selection, exports and tasks keep scan identity.
7. **Rule for later requests.** The core may group by the DICOM hierarchy the converter records (exam, series, part). It never groups by units defined by study logic (acquisition, sequence family, subtraction, copy); those stay in label tables (LBL-*) or outside the app.

**Consequences.**
- \+ Large CT and MR cases become navigable without study logic in the app; ADC series end up next to their DWI by `series_number` (203 of 205 MR sample units).
- \+ Works for any converted dataset; NIfTI-only datasets are unchanged.
- − Explorer rows gain a group level that keyboard navigation, virtualization and the phase filter must handle; the switcher's step order is no longer `scan_idx` order.
- − DWI + ADC as one decision is still not a grouping: it lives as a label-table column.
- Owner docs on acceptance: VIEWER (VW-11), UI_SHELL (UI-08, UI-13), GLOSSARY (exam, series part).

**Rejected alternatives.**
- Grouping by an arbitrary scan-level variable or layer (e.g. an imported `acq_id`): the Explorer and switcher would read arbitrary plugin layers, for a gain the exam and series grouping mostly gives already.
- An `exam` or `acquisition` entity in the index: a core concept and format change for a display need.
- Study dates or UIDs as labels: identifying (NFR-17).
- Sorting by `series_description`: empty for most rows.
