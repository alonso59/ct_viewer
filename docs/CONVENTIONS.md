# Doc conventions (keep tokens low)

Scope: how project docs are written and where facts go.
Read when: creating or editing anything under `docs/` or an `AGENTS.md`.
Depends: INDEX.md (§Ownership), product/SRS.md §1.5.

- Header block: `Scope`, `Read when`, `Depends`. No intro prose. ADRs use the ADR template (`adr/README.md`); routers (`AGENTS.md` files, `INDEX.md`, `adr/README.md`), `SITE.md` and root files have none.
- Target ≤ 200 lines per file. Split rather than grow.
- Keep lines short (one sentence or table row per line, ideally ≤ 300 characters) so agents can read a section by line range; reflow long paragraphs when you touch them.
- Tables and compact schemas over paragraphs. No duplicated examples.
- Requirements: `| ID | Requirement | Pri |`, where Pri is `M` (must), `S` (should), `C` (could) or `—` (retired or out of scope; the text says which). Release targets live in `product/MVP.md`, not in Pri. Grammar and checks: `product/SRS.md` §1.5 (`make check` runs them; `make reqs` reads INDEX.md §Ownership).
- Reference other docs by ID or path; never copy their content.
- `Open questions` section at the end of a file only while something is undecided; move answers to `Decisions`.
- Area maps (`backend/`, `frontend/`, `plugins/` `AGENTS.md`): only owns, entry points, boundaries, tests, change-together, read more. Concepts, not file inventories. Each has a `CLAUDE.md` containing only `@AGENTS.md`.
- Change history belongs in git or `archive/`, not in reference docs.
- `archive/` is frozen history (v2, finished v3 runbook steps and ROADMAP phases, the closed v3 quality audit, retired test-history notes). Do not read or update it unless the task says so.
- `SITE.md` and `_sphinx/` build the published site (`make docs`); agents skip them. Agent-only docs (`INDEX.md`, this file) are excluded from the site in `_sphinx/conf.py`.
