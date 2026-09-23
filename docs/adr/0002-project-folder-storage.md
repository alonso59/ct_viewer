# ADR-0002 Project-folder storage; no database server
Status: Accepted · Date: 2026-09-23

**Context.** PostgreSQL was considered. Deployment must be trivial under udocker (a single container, no services). Projects should be portable like QuPath projects. Voxel data must never go into a DB.

**Decision.** Each project is a folder of JSON, JSONL and Parquet files (PROJECT_FORMAT.md). Curation is an append-only event log; derived state is rebuilt in memory. A single API process is the only writer (BE-01, BE-05). Analytics query Parquet with in-process DuckDB (ADR-0009).

**Consequences.** + No DB container, easy backup (copy the folder), diff-able, portable. + Multi-user is safe through the single writer. − Not suited to many concurrent server processes or huge event logs (> ~1M events); revisit if either becomes real. − `fcntl` locks are unreliable on some network filesystems (OPS-06).

**Rejected.** PostgreSQL (an extra service under udocker; not portable per project). SQLite per project (a good option, but less transparent; keep as a fallback if JSONL performance becomes a problem).
