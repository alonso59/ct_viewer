# ADR-0041 CTFlow: a domain command console over the existing task services
Status: Accepted · Date: 2026-11-03 (owner decisions D1–D7, 2026-11-03)
Extends: ADR-0016 (tasks), ADR-0035 (source operations), ADR-0040 (orchestration pattern). Does not change ADR-0004, ADR-0014, ADR-0018 or ADR-0021.

**Context.** Users want to run conversion, segmentation and radiomics by typing commands and scripts, in the browser and in a Linux terminal (`ctflow`), in the style of an EDA Tcl console. The server already owns durable runs, controls, recovery, selection and preflight; the GUI reaches them through `TaskService`, `WorkspaceTasks` and `SourceOperations`. A console must not become a second engine, an OS shell or a second configuration system. Requirements: CTFLOW.md (CTF-*).

**Decision.**
1. **One server-side interpreter.** The web console, `ctflow` and scripts send text to an interpreter in the backend service layer. It calls only the services the GUI calls; it never writes run files, submits jobs directly or chooses output paths. Clients are thin.
2. **Commands come from task manifests.** Options are the task's `settings_schema`; an optional manifest key gives a short name. A fixed set of core commands wraps existing reads and run controls.
3. **Paths outside a project are refused** for item tasks, with a "create project from this folder" action (PRJ-19). No project is created automatically (D1, ADR-0021).
4. **A small custom Tcl-like language** (D2): `set`, variables, `if`, `foreach`, `proc`, `return`, `source`, `[cmd]` substitution, lists and a limited `expr`. No `eval` of strings, file, environment, process or network access. Embedded Tcl is rejected.
5. **Durable script runs** (D3): a script run is a workspace record that runs as a server job and does not depend on any client. After a restart, resume re-executes the script from the beginning and replays journaled results, so no child run starts twice.
6. **Structured execution journal plus ordinary runs** (D4): each side-effecting call records its resolved request and its child run. Children stay ordinary task runs or source operations. No generic pipeline schema for now.
7. **Mask sets** (D5): with several matching sets the command stops and asks for `-seg <id>`; `-seg default` uses the project default on purpose.
8. **Busy tasks** (D6): a script waits a bounded time for the task to free up, then moves to `attention` until an explicit resume. No automatic retries.
9. **User extensibility is scripts and procedures only** (D7). No user plugins; ADR-0018 stands.
10. **Attribution.** Writes carry the reviewer stamp (ADR-0004) and an origin (`gui`, `console`, `terminal`, `script`) on run and operation records.

**Consequences.**
- \+ One behaviour for GUI and console; plugins gain commands from their manifests.
- \+ What ran is inspectable from the journal and the child run records, not by reinterpreting script text.
- − A small language and a script-run record to own and test; interactive session state is lost on server restart.
- − Item work on a new folder needs an explicit project first.
- Owner docs on acceptance: CTFLOW.md (new, CTF-), INDEX, SRS §3.2, ROADMAP (P7h), GLOSSARY, VISION. TASKS (TSK-10 origin), API, backend ARCHITECTURE, DEPLOYMENT, TESTING and UI_SHELL change in the phase that implements each part.

**Rejected alternatives.**
- Embedded safe Tcl: synchronous evaluation blocks the single API process (BE-01), weak pre-validation, extra image packages.
- Shell or Python in the console: no sound sandbox (R4, R5).
- A hidden or automatic project for paths: rejected by ADR-0021.
- A declarative PipelineSpec now: duplicates manifests, selections and run records.
- A client-side interpreter: work would die with the client and logic would be duplicated per client.
- User plugins: ADR-0018.
