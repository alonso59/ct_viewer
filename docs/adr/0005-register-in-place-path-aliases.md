# ADR-0005 Register data in place with path aliases
Status: Accepted · Date: 2026-09-23

**Context.** CT datasets are hundreds of GB and already live on local or HPC disks. "Upload" means providing `metadata.jsonl` + a data root, not moving bytes.

**Decision.** Projects store `ALIAS:rel/path` references (PRJ-04); aliases map to absolute roots in `project.json`. Import snapshots only the metadata. Relink with fingerprint verification handles moved data (PRJ-05). Paths must resolve inside `ALLOWED_DATA_ROOTS` (OPS-04).

**Consequences.** + No copying, instant import, portable projects. − Projects break if data moves until relinked; − the file-changed-underneath case is detected by fingerprint (IMP `fingerprint_changed`), not prevented.

**Rejected.** Managed store with copy/upload (duplicates TBs). Storing blobs in a DB (see ADR-0002).

**Amended by ADR-0014.** Each alias has a role: `source` (read-only, as here) or `derived` (task outputs only).
