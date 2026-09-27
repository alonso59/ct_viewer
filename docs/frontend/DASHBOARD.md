# Radiomics Dashboard

Scope: QC-oriented visual analytics over a radiomics run (or any task run with `features` output, TSK-09); click-through to the viewer.
Read when: working on `features/dashboard` or `analytics/`.
Depends: domain/RADIOMICS.md, domain/ANALYSIS.md, domain/VARIABLES.md, API-38/39, ADR-0009, ADR-0012.

## Purpose

Find **bad data** (segmentation errors, wrong phase, outliers), understand feature behavior, and get **simple guided statistics** (t-test/ANOVA/correlation with FDR, effect sizes, recommendations; domain/ANALYSIS.md). Models stay outside the app (exports).

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| DB-01 | One dashboard tab per run; views arranged as dockview sub-panels; the arrangement persists per run. | M |
| DB-02 | Global filters on any visible variable (VAR-10) plus phase, scope, side, label, curation status apply to every view. | M |
| DB-03 | Every point, bar or cell that represents items supports hover (ID + value) and click (opens the item in a case tab, same slice context if available). | M |
| DB-04 | Selection in one view (lasso/brush) highlights the same items in all views and can be sent to the Explorer as a filter. | S |
| DB-05 | Heavy computations run server-side (API-38, DuckDB/NumPy); the client receives aggregates, not raw long tables above 50k rows. | M |
| DB-06 | Any view can be exported as PNG (chart) and CSV (underlying data). | S |
| DB-08 | **Analysis panel** (ANA-*): pick question type → variable → (confounder); shows the chosen test + reason, results table (feature, n, effect, p, q), descriptives, and Recommendations. | M |
| DB-09 | Result rows open the feature's distribution split by the analysis variable; recommendation items open the view that shows the problem. | S |
| DB-07 | Color by any categorical variable, phase or curation status; colors come from the categorical palette tokens. | M |
| DB-10 | The outlier table flags an item only when at least a share of its features (default 5 %, and at least one feature) has a robust \|z\| over the threshold (default 3.5); both are adjustable in the view. | M |

## Views

| View | Shows | Params |
|---|---|---|
| Run overview | Items ok/failed/skipped, per-label and per-phase counts, runtime, failures then skips (plain cause, code) → item, items whose phase changed since the run ("phase at run time") | — |
| Feature distribution | Histogram / violin of one feature, split by color variable | feature, split, log-scale |
| Missing / invalid matrix | Feature × item NaN/inf heat map | feature class |
| Correlation heat map | Spearman correlation between features, clustered order | class filter, threshold |
| Embedding scatter | PCA (default) or UMAP (optional dependency) on z-scored features | features, n_components |
| Outlier table | Robust z-score (median/MAD) per feature; flagged items (DB-10: ≥ `min_feature_pct` % of the features, and ≥ 1, over the threshold; owner 2026-09-27), sorted by the number of features over the threshold, then by max \|z\| (owner 2026-09-25); top 10, "Show all"; the per-feature counts cover every item | threshold (default 3.5), `min_feature_pct` (default 5) |
| Feature vs volume | Scatter of a feature against `shape_MeshVolume` (flags size-driven features) | feature |
| Group comparison | Box/violin per group for the selected feature + test result; results table for all features | variable, test override |
| Association | Scatter feature × continuous variable with ρ; ranked table | variable |
| Balance check | Contingency heat map (grouping × confounder) with χ²/Fisher | two categorical variables |
| Phase / side consistency | Paired comparison of the same case across phases or sides (Bland–Altman style) | feature, pair |

## Interaction with curation

- The outlier table and scatter show the curation status badge per item.
- The context menu on an item offers "Open in viewer", "Add to correction queue" (writes a CUR event) and "Copy item_id".

## Decisions

- UMAP is an optional extra (`pip install .[umap]`); PCA is the default embedding.

## Implementation notes

- Views are dockview sub-panels per run (layout in localStorage); the Analysis panel is one of them. Mock mode serves only the QC views.
- "Send to Explorer" sets the Explorer item-id filter (a clearable "N items" chip, combined with the other Explorer filters) and shows the Project view.
- Phase (DB-02, DB-07; AUD-A5-04, owner 2026-09-26): every view and analysis uses the **effective** phase (PHS-03), joined at read time (`IndexStore.effective_phases` → `analytics/data.join_phase`); the run's own value is `phase_at_run` (overview details, tidy and feature exports).
- Values (DB-03; AUD-A3-04, A3-15): formats and units follow UI_SHELL §Implementation notes; axis ticks use the same format.
- Charts (AUD-A3-14): the brush toolbox sits top right above the plot (a legend beside it starts 80 px in); histogram bars sit on a hidden category axis with a visible value axis over the same range (round ticks; the bin range is the tooltip title); chart font sizes read `--fs-badge` / `--fs-panel`.
