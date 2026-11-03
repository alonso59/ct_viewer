# CTFlow console

Scope: the CTFlow command and script console: commands, target resolution, language, script runs, journal, clients, attribution.
Read when: working on the console interpreter, the `ctflow` client, script runs, or a task manifest's `command` key.
Depends: ADR-0041, TASKS.md, SOURCES.md, PROJECT_FORMAT.md (PRJ-19), SEGMENTATION.md, API.md (API-71), NFR.md (NFR-17).

CTFlow is a domain language, not a shell. Every command calls a service the GUI already uses; processing stays task runs (TSK-*) and source operations (TSK-16).
Status: ROADMAP P7h; C1 (attribution, project-run logs), C2 (catalog, targets, one-line evaluation, plan mode; API-72) and C3 (`ctflow` client) are implemented. Rows move their facts into the owning doc (TSK, API, UI, OPS, TST) when the phase that implements them exits.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| CTF-01 | The web console, the `ctflow` terminal client and scripts send text to one server-side interpreter. No client interprets commands or starts runs itself. | S |
| CTF-02 | Commands call only existing services (project and workspace task starts, source operations, selection, validate, preflight, estimate, run controls). CTFlow never writes run files, submits jobs directly or chooses output paths (R1, ADR-0014, TSK-09). The same request through CTFlow and API-45 gives the same run record apart from its origin. | S |
| CTF-03 | Task commands are derived from the loaded task manifests: options are the `settings_schema` properties, validated by the server (TSK-02); target kinds follow `input`, `scope` and `requires`. An optional manifest `command` key gives a short name and option aliases; a name claimed twice makes the later manifest invalid (TSK-01). One catalog of commands, options and help serves every client. | S |
| CTF-04 | Target resolution is deterministic (§Targets): exact `item_id`, exact `case_id` in the current project, or a guarded path. The result is a TaskSelection (TSK-03) or a source path, printed before anything starts. Identity is never inferred from file names. An unknown or ambiguous target is a problem with `actions[]` (SRC-11). | S |
| CTF-05 | An item task given a file or folder that is not an imported source of the current project is refused, with the actions "create project from this folder" (PRJ-19) and "import into this project". No project is created automatically (ADR-0021). `input: source` tasks accept any guarded path. | S |
| CTF-06 | A command that reads masks uses `-seg <id>`, or `-seg default` for the project default on purpose. Without `-seg` it uses the one active set that covers every selected item; when several do, it stops and lists them. | S |
| CTF-07 | The language is the subset in §Language. There is no `eval` of strings, `uplevel`, or file, environment, process or network access; `source` reads only the script library (CTF-17). Limits cap steps, nesting depth, list size and child starts per script; exceeding one stops the script with a clear error. | S |
| CTF-08 | Interactive sessions keep variables and procedures in server memory with an idle timeout. A server restart clears them, and clients say so. Durable work is never session state. | S |
| CTF-09 | Plan mode resolves, validates and preflights each command without starting anything; an estimate (TSK-05) may start a sample job, so it is a separate request. For a script it stops at the first step that depends on a run's result and says so. | S |
| CTF-10 | A script run is a durable workspace record (PLG-07 namespace): script text and hash, parameters, reviewer, origin, status, revision and journal. It runs as a server job and does not depend on any client (§Script runs). | S |
| CTF-11 | Journal: every side-effecting call appends `{key, command, resolved request, child, outcome}`, where child is `(project_id, run_id)` or a source-operation id. The key is deterministic from the script run and the call sequence and is the child start's idempotency key. The journal plus the child run records (TSK-10) are the execution record; there is no separate pipeline schema. | S |
| CTF-12 | After a server restart a non-terminal script run is `interrupted`. Resume re-executes the script from the beginning and returns journaled results for calls already made, so no child starts twice. A changed script hash or parameters refuse resume. | S |
| CTF-13 | When a child start is refused because the task is busy (TSK-12), the script waits for job completions up to a bounded time, then moves to `attention`; only an explicit resume continues it. Failed children are never retried automatically. | S |
| CTF-14 | Cancel and pause on a script run stop dispatch and forward to the active child through its existing controls (TSK-15, API-46, API-69). Children stay ordinary runs in the Jobs panel and carry the parent script run id in their provenance. | S |
| CTF-15 | Writes need a reviewer (`X-Reviewer`, ADR-0004). `ctflow` takes it from `--reviewer`, an environment variable or a saved local setting. Task runs, workspace runs, source operations, batch plans and script runs record the reviewer and an origin `{client: gui \| console \| terminal \| script, session?, script_run_id?}`; requests without one are `gui`. | S |
| CTF-16 | Clients show run records, job events and API-71 logs, never a status of their own. API-71 gains project-run and script-run kinds. Output levels: normal (target, run id, status changes), verbose (preflight reasons, effective settings, item failures), trace (interpreter steps, journal). All text is redacted (NFR-17). | S |
| CTF-17 | The script library holds saved scripts and procedures in the workspace CTFlow namespace and optionally per project; parameters and help come from leading comments. Nothing is stored in a source root (R1). User extensibility is scripts and procedures only (ADR-0018). | S |
| CTF-18 | `ctflow` is one standard-library Python file with no install (R4). It reaches `http://127.0.0.1:$PORT/api/v1` (PORT from the `./rw` `.env`) or `--url`. Modes: interactive, `-c`, a script file, `--detach`, `runs`, `status`, `logs`, `attach`, `cancel`; exit codes follow the final status. | S |
| CTF-19 | The web console is a bottom-panel tab (UI-02) with completion from the command catalog and the existing log view; it is hidden on view-only links (UI-26). | C |
| CTF-20 | GUI journaling: GUI actions shown as the equivalent CTFlow command. Needs one central command dispatch in the frontend first. | C |

## Concepts

| Concept | Is | Existing abstraction |
|---|---|---|
| Task | The atomic processing capability | Task manifest + run protocol (TSK-*) |
| Run | One execution of a task | Task run, workspace run or source operation |
| Command | A name, options and target over one task or one core service call | New, thin |
| Script | CTFlow text: commands plus control flow | New |
| Script run | One durable execution of a script | New, modelled on the batch plan (ADR-0040) |
| Journal | The resolved calls of a script run and their children | New, part of the script run |
| Preset | A saved script or procedure with parameters; a single command is a valid preset | Task defaults and profiles cover one step |

## Commands

- Task commands: one per available task (TSK-01), named by the manifest `command` key or the task id; `voi` appears when its plugin ships a task.
- Core commands:
  - context: `project`, `cases`, `items`, `sets`, `detect`;
  - runs: `runs`, `status`, `logs`, `wait`, `cancel`, `pause`, `resume`, `retry`;
  - setup: `project create` (PRJ-19), `import`;
  - help: `help`.
- Every core command wraps an existing endpoint's service; view-only links get none.

## Targets

1. An exact `item_id` of the current project: that item.
2. An exact `case_id` (`CASE_ID_RE`) of the current project: all active items of the case, narrowed by `-scope` and `-phase`.
3. A path: guarded (BE-02), then `detect()` (SRC-01). Source tasks use it as the source. Item tasks need it to be an imported source of the current project, else CTF-05.
4. Masks: CTF-06.

## Language

- Words, `"…"`, `{…}`, `$var`, `[cmd]`; one command per line or `;`; `#` comments.
- Built-ins: `set`, `if`/`elseif`/`else`, `foreach`, `proc`, `return`, `break`, `continue`, `source`, `list`, `llength`, `lindex`, `lappend`.
- `expr`: numbers, strings, arithmetic, comparison and boolean operators only.
- Options are `-name value`; a boolean option alone means true.

## Script runs

- Statuses: `queued`, `running`, `waiting` (busy task, CTF-13), `attention`, `pausing`, `paused`, `cancelling`, `cancelled`, `completed`, `completed_with_errors`, `failed`, `interrupted`.
- Driven by a job driver; waiting re-enters on job completion (as the batch plan's `nudge`). Recovery joins the startup recovery list.
- Child failure policy: the script stops at a failed child; a partially failed child continues only when the script says so.

## Implementation notes

- Shipped command names: `dicom2nii` (`dicom.convert`), `radiomics`, `segment` (`segment.nnunet`, `-gpus` = `gpu_cap`). Adding the key changed the nnU-Net manifest hash, which its resume pins: nnU-Net runs paused or interrupted before that release start again instead of resuming, and the host runner's `PLUGINS_ROOT` copy must be updated with the image.
- `dicom2nii` starts a durable source operation with its analysis (API-69); `convert <operation>` then converts it, as the converter window does.
- `ctflow` (C3, `scripts/ctflow.py`, OPS-21): interactive console, one command (`-c` or the words after the options) followed to its end, `--detach`, `--plan`, `--json`, `attach`, `logs [-f]`, `status`, `cancel`, `runs`. Exit codes: 0 completed, 1 failed/with errors/interrupted, 2 refused, 3 cancelled/paused, 130 stopped following. The console's `project` is held by the client until sessions (CTF-08); script files and `--detach` of a script come with C4/C5.
- Test-only tasks are callable by id and not listed. Numbers that look like integers stay integers, so settings hash as the GUI's do.

## Deferred to implementation

Package and endpoint names, script file extension, session timeout, limit values, the bounded wait, journal file format, polling or SSE in `ctflow`, and whether a workspace event stream lands with CTF-16.
