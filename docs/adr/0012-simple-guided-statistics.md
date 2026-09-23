# ADR-0012 Simple guided statistics in-app
Status: Accepted · Date: 2026-09-23 · Supersedes: the "dashboard for QC only, no p-values" default (DASHBOARD.md, VISION out-of-scope)

**Context.** Users want quick insights from extracted features (t-test, ANOVA, correlation) and guidance on what to do next, while serious modeling stays outside the app.

**Decision.** Add a small analysis layer (ANALYSIS.md): four question types (explore, compare groups, association, balance check), automatic parametric/nonparametric choice with a stated reason, BH-FDR q-values and effect sizes on every result, a one-row-per-case default unit, and rule-based recommendations (small n, confounders, size effect, redundancy, compositional variables…). Everything exports as tidy CSV + `spec.json`. Computed server-side with SciPy (statsmodels turned out unnecessary).

**Consequences.** + Useful insights without leaving the app; + guards against the common pitfalls (multiplicity, pseudo-replication, scanner effects). − Risk of over-interpretation: results are labelled exploratory and always show n, q and effect size. − Adds SciPy to the image (~40 MB).

**Rejected.** No statistics at all (users asked for it). Full statistical workbench with models (out of scope; export instead).
