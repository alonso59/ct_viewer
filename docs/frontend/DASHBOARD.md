# Radiomics Dashboard

Scope: QC-oriented visual analytics over a radiomics run; click-through to the viewer.
Read when: working on `features/dashboard` or `analytics/`.
Depends: domain/RADIOMICS.md, API-38, ADR-0009.

## Purpose

Find **bad data** (segmentation errors, wrong phase, outliers) and understand feature behavior.
The dashboard is **not** an inferential statistics tool: no p-values, no models (see VISION §Out of scope). Export is the path to real statistics.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| DB-01 | One dashboard tab per run; views arranged as dockview sub-panels; the arrangement persists per run. | M |
| DB-02 | Global filters (group, phase, scope, side, label, curation status) apply to every view. | M |
| DB-03 | Every point, bar or cell that represents items supports hover (ID + value) and click (opens the item in a case tab, same slice context if available). | M |
| DB-04 | Selection in one view (lasso/brush) highlights the same items in all views and can be sent to the Explorer as a filter. | S |
| DB-05 | Heavy computations run server-side (API-38, DuckDB/NumPy); the client receives aggregates, not raw long tables above 50k rows. | M |
| DB-06 | Any view can be exported as PNG (chart) and CSV (underlying data). | S |
| DB-07 | Color by group, phase or curation status; colors come from the categorical palette tokens. | M |

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
| Phase / side consistency | Paired comparison of the same case across phases or sides (Bland–Altman style) | feature, pair |

## Interaction with curation

- The outlier table and scatter show the curation status badge per item.
- The context menu on an item offers "Open in viewer", "Add to correction queue" (writes a CUR event) and "Copy item_id".

## Decisions

- UMAP is an optional extra (`pip install .[umap]`); PCA is the default embedding.
