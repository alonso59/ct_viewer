# ADR-0048 Agent interface over CTFlow
Status: Accepted · Date: 2026-11-05
Extends: ADR-0041 (CTFlow), ADR-0004 (reviewer stamp).

**Context.** Driving the app through raw HTTP costs most tokens on guessing contracts: fences (409), hidden step order, no way to reassign a batch's operation short of editing `plan.json`. The long-term goal is an agent that builds an analysis workspace from a prompt, which the user then edits in the GUI.

**Decision.**
1. An agent acts only through validated operations on the same services as the GUI (CTFlow and the API), never by editing files.
2. The MCP server is `scripts/rw-mcp.py`: standard library, stdio, a thin client of CTFlow. It holds only its CTFlow session id. Its origin client is `agent`. Acting is opt-in per call: a query tool always runs in plan mode; a separate run tool executes and is approved by the user's MCP client.
3. CTFlow gains what an agent needs: resume and retry-failed for source operations, `diagnose` (counts and top failure messages, redacted), and batch-plan commands including reassigning a batch's operation. The reassign endpoint validates plan revision, batch state and operation ownership.
4. Zones:

| Zone | Agent may |
|---|---|
| Source roots | Read only (R1) |
| Derived outputs and runs | Yes, through task operations |
| Project definitions | Yes, author `agent`, with undo (deferred) |
| Clinical data and labels | Propose; a person confirms (deferred) |
| Delete or overwrite | Recycle bin only, with confirmation |

5. Analysis workspace (principle only): one declarative, versioned, server-stored definition (inputs, panels from the existing view catalog, a report whose numbers the server inserts), edited by GUI and agent alike. The schema waits for the Cohort work. Agents receive aggregates, never patient rows (R5, NFR-17).

**Consequences.** One implementation of every action; the agent inherits fences, reviewer stamps and redaction. Definition undo and the workspace schema are separate later decisions.

**Rejected alternatives.** A second implementation of services inside the MCP. An MCP endpoint in the backend. An SDK dependency (R4). Agent-editable React code as the composition mechanism.
