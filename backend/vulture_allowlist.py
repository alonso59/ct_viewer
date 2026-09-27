"""Vulture allowlist for `make deadcode` (AUD-A6-18; docs/ops/TESTING.md §Dead code).

Vulture runs at confidence >= 80 (unused imports, unreachable code, unused arguments), so
FastAPI routes, pydantic fields and validators (60 %: used by the framework, not by name) are
not reported. List a name here only for a false positive that the gate does report, as a bare
expression with a comment saying who uses it, e.g. a FastAPI dependency parameter that is
needed only for its side effect:

    _.request  # FastAPI injects it; the route reads nothing from it

Prefer a real fix first (`@pytest.mark.usefixtures(...)` for a fixture requested only for its
side effect; `_`-prefixed names for arguments a signature needs). Empty on 2026-09-27 (FB9).
"""
