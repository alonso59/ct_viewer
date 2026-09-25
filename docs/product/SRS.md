# Software requirements specification (SRS)

Scope: the IEEE 29148 frame around every requirement of v3; the requirement tables are generated from the owner docs at build time.
Read when: you need all requirements at once, the requirement grammar, or how requirements are verified. For one area read its owner doc (INDEX §Ownership).
Depends: VISION (PRD), MVP, GLOSSARY, NFR, TESTING, INDEX §Ownership, AGENTS.md R1..R9.

## 1 Introduction

### 1.1 Purpose

One view of what Radiology Workbench v3 must do, for reviewers and release decisions. It restates nothing: each row is rendered from the one owner doc that defines it (R8).

### 1.2 Scope

Product, users and boundaries: VISION §Purpose, §In scope, §Out of scope. The v3.0 cut: MVP.md.

### 1.3 Definitions

GLOSSARY.md. Priorities: §1.5.

### 1.4 References

Owner docs as listed in INDEX §Ownership; decisions in `adr/README.md`; hard rules R1..R9 in `AGENTS.md` (repository root).

### 1.5 Conventions and checks

| Rule | Detail |
|---|---|
| ID | `XXX-nn`: a prefix from INDEX §Ownership and two digits. IDs are never reused; a removed requirement keeps its row with Pri `—` |
| Tables | By header: `ID \| Requirement \| Pri` (functions, constraints) · `ID \| Requirement \| Pri \| Target` (quality, NFR) · `ID \| Method & path \| Purpose \| Ref` (interfaces, API) · `ID \| Layer \| Tooling \| Covers` (verification, TST) · `ID \| Gate \| Check \| Status` (release gates, MVP). Any other `ID` table holds no `XXX-nn` rows |
| Pri | `M` must · `S` should · `C` could · `—` retired or out of scope (the text says which). Every `M` is in v3.0 unless MVP.md defers it |
| Cells | A literal `\|` is written `\|`, also inside code spans; a table has no blank lines |
| Checks | `make check` runs `docs/_sphinx/reqs.py check` (stdlib, < 1 s). Errors: duplicate ID, unknown prefix, ID defined outside its owner doc, cell count ≠ header, ID rows without a header, Pri outside the set, a prefix missing from (or repeated in) the tables of §3. Warning: an ID cited but never defined |
| Build | `make docs` builds the site (Sphinx + MyST, `-W`, config `docs/_sphinx/`, root `SITE.md`) into `build/docs/`; IDs, `ADR-nnnn` and `path.md` mentions become links there. `make docs-srs` writes the review table to `build/docs-srs/`; `make trace` writes code/test citations to `build/trace/`. Nothing generated is committed |

## 2 Overall description

| Topic | Where |
|---|---|
| 2.1 Product perspective | VISION §Purpose, ADR-0010 (layout), ADR-0007 (one image) |
| 2.2 Product functions | VISION §Journeys G1..G4 |
| 2.3 User characteristics | VISION §Users |
| 2.4 Constraints | AGENTS.md R1..R9; ADR-0002, ADR-0004, ADR-0014; §3.4 |
| 2.5 Assumptions and dependencies | VISION §Assumptions; NFR design envelope |
| 2.6 Apportioning | MVP §After v3.0; ROADMAP |

## 3 Specific requirements

Columns added by the build: **Journeys** (the G paths whose refs include the row, VISION §Journeys) and **Tests** (number of test files citing the ID, AUD-A4-01; `—` = none yet).

### 3.1 External interfaces

```{srs-table} API
```

### 3.2 Functions

```{srs-table} PRJ IMP SRC TSK DCM ANZ PHS PLG LBL CUR RAD VAR ANA REC UI VW DB
```

### 3.3 Quality

```{srs-table} NFR
```

### 3.4 Design and runtime constraints

```{srs-table} BE FE OPS
```

## 4 Verification

Test layers and tools, generated from TESTING:

```{srs-table} TST
```

A test cites the IDs it covers in its name or docstring (AUD-A4-01). Release verification: MVP.md §Release gates.
