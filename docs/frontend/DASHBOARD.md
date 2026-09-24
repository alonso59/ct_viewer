# Radiomics Dashboard

Scope: QC-oriented visual analytics over a radiomics run; click-through to the viewer.
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

## Views

| View | Shows | Params |
|---|---|---|
| Run overview | Items ok/failed, per-label counts, runtime, error list → item | — |
| Feature distribution | Histogram / violin of one feature, split by color variable | feature, split, log-scale |
| Missing / invalid matrix | Feature × item NaN/inf heat map | feature class |
| Correlation heat map | Spearman correlation between features, clustered order | class filter, threshold |
| Embedding scatter | PCA (default) or UMAP (optional dependency) on z-scored features | features, n_components |
| Outlier table | Robust z-score (median/MAD) per item; top-N items and features | threshold (default 3.5) |
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

## Implementation notes (P6-FE)

- Views are dockview sub-panels per run (layout in localStorage); the Analysis panel is one of them. Mock mode serves only the QC views.
- "Send to Explorer" copies the item ids and opens the first item until the explorer supports an item-id filter.
