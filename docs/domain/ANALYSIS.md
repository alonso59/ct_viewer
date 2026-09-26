# Radiomics Analysis (simple, guided)

Scope: analysis spec, unit of analysis, automatic test choice, multiple comparisons, recommendations, export.
Read when: building analysis computation (backend `analytics/`) or its UI (DASHBOARD.md).
Depends: RADIOMICS.md, VARIABLES.md, ADR-0012.

## Principle

Keep it simple: quick insights in-app, serious modeling outside (exports).
The user states **what question** they ask; the app picks a sensible test, explains why, and flags pitfalls.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| ANA-01 | An analysis = run + filter + unit + question type + variable (+ optional confounder). Saved in `analyses/{analysis_id}/spec.json`, re-runnable. | M |
| ANA-02 | Question types (§Tests): **Explore**, **Compare groups**, **Association**, **Balance check**. The UI offers only types valid for the chosen variable's type. | M |
| ANA-03 | Unit of analysis defaults to **one row per case**: one label, one phase (project phase priority), one scope. If > 1 item per case remains, the user picks: first by phase priority, or mean. | M |
| ANA-04 | Automatic test choice (§Tests) with a one-line reason; the user may switch to the alternative test. | M |
| ANA-05 | Every feature tested gets p, **q (Benjamini–Hochberg FDR)** and an effect size. Results table sorts by q, then effect size. | M |
| ANA-06 | Minimum n: groups with < 5 rows are excluded from tests (still shown descriptively). | M |
| ANA-07 | Descriptives per group: n, missing, median, IQR, mean, SD. | M |
| ANA-08 | After computing, show **Recommendations** (§Rules), each linking to the view that shows the problem. | M |
| ANA-09 | Export: tidy CSV (unit rows × features + variables), results CSV, and `spec.json` so the same analysis can be redone in Python/R. | M |
| ANA-10 | Paired comparison (same case across phases or sides): paired t / Wilcoxon signed-rank. | C |
| ANA-11 | Out of scope in-app: multivariable models, ML, survival, mixed models, ComBat harmonization. Recommend them; do them outside. | — |

## Tests

| Question | Variable type | Default test | Alternative (auto when any group n < 15 or Shapiro–Wilk p < 0.05) | Effect size |
|---|---|---|---|---|
| Explore | none | — (distributions, correlation, PCA, outliers: DB views) | — | — |
| Compare groups | categorical, 2 levels | Welch t-test | Mann–Whitney U | Cohen's d / rank-biserial r |
| Compare groups | categorical, ≥ 3 levels | Welch ANOVA | Kruskal–Wallis | η² / ε² |
| Association | continuous | Spearman ρ | Pearson r (user choice) | ρ / r |
| Balance check | categorical × categorical (e.g. group × vendor) | χ² | Fisher exact (2×2 or expected < 5) | Cramér's V |

## Recommendation rules

| Code | Trigger | Message (short) |
|---|---|---|
| REC-SMALL-N | any group n < 10 | Small groups: results unstable; treat as exploratory. |
| REC-IMBALANCE | largest/smallest group > 4 | Groups are imbalanced; prefer nonparametric tests and report n. |
| REC-MISSING | variable missing for > 30 % of cases | Analysis uses only {n} of {N} cases; check whether missingness is random. |
| REC-CONFOUNDER | a `confounder` variable is associated with the grouping (balance check q < 0.05) or with > 20 % of significant features | Possible scanner/protocol effect; stratify, or harmonize outside the app (e.g. ComBat). |
| REC-VOLUME | a significant feature has \|ρ\| > 0.8 with mesh volume | Feature may just reflect size; check it against volume. |
| REC-REDUNDANT | clusters of features with \|ρ\| > 0.9 | Many redundant features; keep one per cluster for modeling. |
| REC-NONINDEP | more than one item per case in the unit | Rows are not independent; aggregate per case. |
| REC-NO-SIGNAL | no feature with q < 0.1 | No robust differences; consider effect sizes and power before concluding. |
| REC-MODALITY | mixed modalities (e.g. CT + MRI) in the unit | Intensity features are not comparable across modalities; filter to one. |
| REC-COMPOSITIONAL | ≥ 2 continuous variables summing to ≈ constant (e.g. `hb + lb ≈ 100`) | Variables are compositional; analyze one, or use a derived dominant/bin variable. |

## Storage

`analyses/{analysis_id}/spec.json`, `results.parquet`, `descriptives.parquet`, `recommendations.json`, `exports/`.

## Implementation notes (P6-BE)

- Export: `GET …/analyses/{aid}/export?file=tidy|results|descriptives|spec`; the tidy export omits `sensitive` variables.
- Phase (ANA-03, PHS-03; AUD-A5-04): the unit's phase and phase priority use the effective phase, joined at read time; the tidy export adds `phase_at_run` (the run's value).
- Unit: `{label, scope, phase, aggregate: first|mean|none}`. Colour/split: `{kind: variable|phase|scope|side|label|curation_status, name}`. Filters body: `{var, phase, scope, side, label, status, item_ids}`.
- R×C Fisher is a seeded permutation test. Everything uses SciPy (no statsmodels).
- Views and analyses currently compute in a thread in the API process, not a job worker; fine at fixture scale, revisit near 3,000 cases (BE-12).
