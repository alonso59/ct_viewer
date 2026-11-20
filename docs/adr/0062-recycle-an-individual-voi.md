# ADR-0062 Recycle an individual VOI

Status: Accepted · Date: 2026-11-20

Supersedes the scan-only scope of ADR-0029. Extends ADR-0058 to individual VOI entries.

A reviewer can keep the full scan and one VOI while discarding a different VOI from
the same scan. Use the audited recycle and restore transaction for the selected VOI.
The same operation updates other active projects that index its image. The manifest
and token identify the intended scope. CUR-16 and CUR-17 own the behavior and
API-66 and API-82 own the contracts.
