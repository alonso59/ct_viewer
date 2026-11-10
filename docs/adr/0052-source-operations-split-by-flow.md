# ADR-0052 Source operations: one record owner, flows in their own modules
Status: Accepted (owner delegated the decision in the session brief) · Date: 2026-11-10
Extends: ADR-0035 (durable DICOM source operations). No change to on-disk formats, HTTP contracts or behavior.

**Context.** `backend/app/tasks/source_operations.py` kept one class of about 45 methods (1,542 lines) for the whole durable DICOM lifecycle. Models, plans, inventory access, import commit and retention were already split out; what stayed mixed four flows that share only the operation record: the import adapter, Open sessions, read-only inventory queries and restart recovery. Reading or changing one flow meant reading all of them.

**Decision.**
1. **`SourceOperations` owns the record and the dispatch.** It alone reads and writes `operations/<id>/operation.json` and the creation receipts (`get`, `list`, `_write`, `_persist`, `_dir`, `_attempt_dir`), holds the per-operation lock keys (`_source_operations`, `_source_operation:<id>`), the control fencing (`_check_control`, `_confirm_replay`, the native-run control trio), creation (`start`), dispatch and the worker drive (`_submit`, `_drive`, `_drive_claimed`, `_finish_*`), and the commands `view`, `estimate`, `convert`, `cancel`, `resume`. The drive stays here because its outcome mapping, crash cleanup and control writes are one consistency unit, and tests patch `source_operations.run_dicom_worker`.
2. **Flows are module functions over that owner**, as `source_retention.prune_inventories(operations)` already is. Each takes the `SourceOperations` instance, changes the record only through its `_write`, and imports the owner for type checking only:
   - `source_queries.py`: inventory-backed reads (`detection`, `plan_page`, `patient_ids`, `series_page`, `require_inventory`).
   - `source_open_session.py`: the Open session (`open_session`, `save_open_session`, `close_open_session` and their loaders). Not `source_open.py`: that file's own bytes are part of the prepared-Open reader identity, so code moved into it would make every Open session prepared by the previous release count as changed after an upgrade. The same holds for every module a cache identity hashes (`scan`, `files`, `convert`, `pipeline`, the analyzer checkpoint's `phase` and `text`, `open`, `dicom_stage`, `header`, `npy_convert`): a behavior-preserving refactor leaves them byte-identical.
   - `source_import.py`: the import adapter (`import_view`, `save_import`, `start_import`, `submit_import`), next to `commit_with_annotations`.
   - `source_recovery.py`: restart evidence and recovery (`execution_state`, `recover_source`, `recover_all`).
3. **Callers move with the code.** API routes, `source_batches` and `main` call the flow functions directly; no forwarding methods stay on the class. Tests that reached a moved private member follow it without changing what they assert.
4. **Order and stop rule.** One extraction per commit, in the order above (least shared state first), each green on the tests it names before the next starts. A step that fails twice is dropped and reported; the steps before it stay.

**Consequences.**
- + Each flow is readable alone; the record, the locks and the drive have one owner. `source_operations.py` goes from 1,542 to about 1,040 lines.
- − Flow modules call the owner's underscored record methods; that is the package's internal contract, documented here rather than renamed, so tests and receipts stay untouched.
- − `cancel` and `resume` still dispatch over import, native-run and source branches inside the owner; splitting them by branch changes control flow and is left for a separate, test-first change.

**Rejected.** A class per flow composed into the owner (adds forwarding or changes every caller's attribute path for no gain over functions); making the record methods public (renames across tests with no behavior benefit); moving the drive out (breaks the worker patch point and splits one consistency unit).
