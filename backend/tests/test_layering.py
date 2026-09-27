"""BE-ARCH §Layering (AUD-A6-10): `api/v1` → services → `core`. No service package imports the API
layer, and no new mutual dependency between packages appears (runtime imports, function-local
ones included; `if TYPE_CHECKING:` blocks are left out: they are erased at run time)."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
# Top-level modules and the API layer may import anything
TOP = {"api", "main", "context", "config", "__init__"}

# Mutual package dependencies that existed when this check was added (2026-09-27, FB8). They are
# query-time joins (cases with curation and variables) and shared models; breaking them needs models
# moved down to `core` or the joins moved up: deferred. The list may only shrink.
KNOWN_MUTUAL = {
    ("curation", "ingest"),
    ("curation", "projects"),
    ("ingest", "phase"),
    ("ingest", "projects"),
    ("ingest", "sources"),
    ("ingest", "variables"),
    ("labeling", "variables"),
    ("sources", "tasks"),
}


class _Imports(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found: list[tuple[str, int]] = []

    def visit_If(self, node: ast.If) -> None:
        t = node.test
        name = t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else ""
        if name == "TYPE_CHECKING":
            for n in node.orelse:
                self.visit(n)
            return
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module and node.module.startswith("app."):
            self.found.append((node.module, node.lineno))

    def visit_Import(self, node: ast.Import) -> None:
        self.found += [(a.name, node.lineno) for a in node.names if a.name.startswith("app.")]


def package_graph() -> dict[str, dict[str, list[str]]]:
    g: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for f in sorted(APP.rglob("*.py")):
        rel = f.relative_to(APP)
        pkg = rel.parts[0] if len(rel.parts) > 1 else rel.stem
        v = _Imports()
        v.visit(ast.parse(f.read_text(encoding="utf-8")))
        for module, line in v.found:
            target = module.split(".")[1]
            if target != pkg:
                g[pkg][target].append(f"{rel}:{line}")
    return g


def test_services_never_import_the_api_layer() -> None:
    g = package_graph()
    bad = {p: deps["api"] for p, deps in g.items() if p not in TOP and "api" in deps}
    assert bad == {}


def test_no_new_mutual_package_dependency() -> None:
    g = package_graph()
    mutual = {
        (a, b)
        for a in g
        for b in g[a]
        if a < b and a not in TOP and b not in TOP and a in g.get(b, {})
    }
    new = {(a, b): (g[a][b][:2], g[b][a][:2]) for a, b in mutual - KNOWN_MUTUAL}
    assert new == {}, "a new two-way package dependency; move the shared part down (core)"
