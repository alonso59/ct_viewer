# ADR-0042 Standalone DICOM converter package with per-unit input pinning
Status: Accepted · Date: 2026-11-03 (owner decisions D1–D11, DICOM_STANDALONE_PLAN.md)
Supersedes: ADR-0035 §5 only for the whole-run input content pin; verified resume, fencing and all other decisions remain in force. Extends: ADR-0017 §6 (standalone CLI), ADR-0035. Does not change ADR-0014, ADR-0020, ADR-0021 or ADR-0040.

**Context.** `plugins/dicom` is the only converter: the backend, Open mode and the CLI (DCM-09) call it, and it never imports `app`. Standalone use on sources of 10⁵–10⁶ files is limited by:
- a generic `plugins` namespace that only works from a checkout, and Linux-only code;
- a CLI that writes fewer artifacts than a workspace dataset and accepts only part of the settings;
- a whole-run pin that hashes every selected input before the first pixel, holds one entry per file in memory and is recomputed on every resume;
- serial execution, and durable discovery that lives only in the backend;
- commit identities that pin all settings and reader versions, so later incremental runs conflict after any settings or reader change. Requirements: DCM-26..34; plan: DICOM_STANDALONE_PLAN.md.

**Decision.**
1. **Package.** The conversion core and the metadata rules it calls move unchanged into the distribution `rw-dicom` (import `rw_dicom`, command `rw-dicom`) under `plugins/dicom/src/`. ct_viewer imports it directly. `plugins.dicom.task:run`, a byte-identical `task.json` (so manifest hashes hold) and `python -m plugins.dicom.cli` remain. The package imports neither `app`, `plugins` nor CTFlow. Python 3.12 and Linux first; no new Linux-only calls.
2. **One settings schema.** `task.json` `settings_schema` stays authoritative; the package ships a generated copy that CI checks for drift. Every surface validates with one normalizer. Execution parameters (workers, memory budget, failure limit, mixed-version acknowledgment) stay out of the settings hash, the commit identity and the resume request.
3. **One artifact contract.** Standalone output is a workspace dataset (DCM-14) written by the same emission code. Manifests are written atomically and durably; private run state lives in a 0700 subtree. Converted datasets are not assumed to be shareable (DCM-05); export is deferred.
4. **Per-unit input pinning.** A unit hashes its inputs (SHA-256) through the guarded descriptors immediately before decoding, hashes them again afterwards and records the manifest in its commit. The run pin keeps settings, versions, identity and one stat digest per unit. This replaces the whole-run content snapshot:
   - Each unit is internally consistent, but units are not pinned at one common moment.
   - A change to a not-yet-converted unit between attempts is detected by size, mtime or ctime, not by content.
5. **Strict verification stays the default.** Reusing a committed unit verifies the SHA-256 of its inputs and outputs. Metadata-based detection, whose limits on network and emulated file systems are documented in the plan, never verifies committed units. Weakening this needs a new ADR backed by benchmarks, regression evidence and file-system compatibility tests, including network storage.
6. **Versions are provenance.** An unfinished run resumes only with its pinned versions. A later run may reuse verified units from other versions; each keeps its recorded versions, and reuse never claims reproduction.
   - Converting new units into a dataset whose committed units carry other versions requires an explicit per-run acknowledgment, recorded together with per-version unit counts.
   - Commit identity uses only the dataset-fixed settings (`anonymize`, `sidecars`, `include_modality_prefix`, salt), which a dataset cannot change.
7. **Bounded execution.** Coordinator memory scales with the number of series, not files. A bounded set of spawned worker processes converts units under a total memory budget, inside the existing owned attempt (ADR-0035 §4). Outputs do not depend on worker count or completion order. ct_viewer keeps one worker until benchmarks set its default.
8. **Incomplete datasets.** A dataset with failed or pending units keeps an explicit incomplete status and imports only with explicit acknowledgment. Converted units arrive with their annotations; failed and pending rows stay distinguishable, excluded with their original reasons; diagnostics are preserved. Nothing incomplete is shown as complete, and `dataset.json` still marks only complete, sealed datasets.

**Consequences.**
- \+ One converter for the GUI, API, CTFlow, Python and the CLI; standalone output imports like a workspace dataset.
- \+ No serial whole-source hash pass, an early first output, and memory bounded by the number of series.
- \+ Settings and reader upgrades no longer break incremental conversion; mixed versions are visible and deliberate.
- − Moving the files is a one-time invalidation: inventories rescan, Open caches and timing history reset, and unfinished phase analyses must finish first.
- − An edit that preserves the size, mtime and ctime of a not-yet-converted unit between attempts is no longer detected.
- − New owner rules: DCM-26..34 (`S`, not a v3.0 dependency, with mandatory release gates), two QC codes for incomplete conversion (INPUT_METADATA.md), additive API acknowledgments.

**Rejected alternatives.**
- Keep `plugins.dicom` as the public namespace: a generic top-level `plugins` package collides in shared environments.
- `sys.modules` aliases or star-import shims: mypy can't follow them, and module-attribute settings would stop reaching the real module.
- Generate `task.json` from the package, or reference the schema from the loader: the first changes manifest bytes and resume pins, the second changes the loader.
- `ProcessPoolExecutor` on Python 3.12: a broken pool names no culprit, and running workers can't be killed through a public API.
- Stat-only verification now; writing `dataset.json` for incomplete datasets, which older readers and a rollback would treat as sealed.
