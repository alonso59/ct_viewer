# ADR-0059 Derived tumor regions as a task plugin; combined runs and label pairs for analysis
Status: Accepted · Date: 2026-11-18
Extends: ADR-0006 (radiomics engine adapter), ADR-0015 (segmentation sets), ADR-0016 (tasks and plugins).

**Context.** The ccRCC study needs radiomics of the whole tumor, its core (eroded 3 mm), its
rim (tumor minus core) and a peritumoral band of kidney 2–5 mm outside the tumor, measured in
millimetres on anisotropic scans. The research pipeline already derives these regions outside
the app. Radiomics extracts one label of one segmentation set per run, a dashboard and an
analysis read one run, and the paired view compared only phases or sides. On 2026-11-18 the
owner chose regions over the whole tumor of a scan (not per lesion), on complete and VOI items
alike, and asked to analyze the regions together with the tumor in the app.

**Decision.** RAD-15, RAD-16 and ANA-10 own the behavior; API-83 the combine endpoint.
- A first-party plugin `regions` contributes the builtin task `regions.derive`. It reads the
  selected set like `voi.extract` and writes a new task segmentation set: one label map per item
  with `tumor_core`, `tumor_rim` and `peritumoral`, which never overlap. The tumor stays in its
  source set. Registration, provenance, resume and the task form are the existing task protocol;
  the radiomics engine, planner and worker are unchanged.
- A *combined run* joins finished runs with the same settings and engine into a new finished run
  (`sources`), so the dashboard and the analysis read the tumor and its regions as one run. Each
  (item, label) comes from one source.
- The paired view also pairs two labels of the same item, and tests every feature with a paired
  t-test or Wilcoxon signed-rank (BH q over the features).

**Consequences.** The project label map gains the three region labels the first time the task
runs. The algorithm is a port of the research pipeline's `compute_derived_masks`, kept equal by
a parity test, because plugins cannot import the research repository. Regions with no voxels or
below a size are flagged in the run's `qc.jsonl` and reach radiomics as recorded failures, never
silently dropped. Per-lesion regions need a radiomics unit finer than (item, label) and are not
offered.

**Rejected alternatives.** Deriving regions inside the radiomics run (it would rebuild set
registration and change the radiomics run record); a mask service in the backend with its own
routes (duplicates the task protocol); several segmentation sets per radiomics run (changes the
radiomics selection, planning and resume); dashboards over several runs (every view and analysis
would take a run list).
