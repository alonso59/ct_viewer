# ADR-0004 No accounts; link sharing; reviewer name stamp
Status: Accepted · Date: 2026-09-23

**Context.** Users want zero-friction collaboration: create a project, share a link, and others open it. No user management.

**Decision.** No authentication or roles. Project access is by the ULID link. Authorship is a free-text reviewer name kept in browser `localStorage` and sent as `X-Reviewer` (CUR-01). The server binds to localhost by default; remote access goes through VS Code port forwarding.

**Consequences.** + Nothing to administer. − Anyone who reaches the port can read and write every project; ULIDs are **not** a security boundary. − Reviewer names are self-declared, so the audit trail is advisory, not proof of identity. On shared servers, other local users can reach localhost ports too. This risk is accepted, so projects can only be archived, never deleted (PRJ-06). Deploy only on trusted hosts and networks.

**Rejected.** Shared bearer token (v2): friction without real identity. Accounts and roles: out of scope. A future ADR may add optional auth behind a reverse proxy.

**Amended by ADR-0019.** A project may also have a view-only link (`/v/{token}`) served by read-only routes; still no accounts.
