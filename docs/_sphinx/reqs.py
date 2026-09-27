"""Requirement tables: one parser for the docs site, `make docs-srs`, `make check` and `make trace`.

Stdlib only (Sphinx is imported lazily by `setup`). Grammar and rules: product/SRS.md §1.5.

CLI (from the repo root):
    python3 docs/_sphinx/reqs.py check        # validate; exit 1 on errors (`make check`)
    python3 docs/_sphinx/reqs.py srs [OUT]    # OUT/srs.csv + OUT/srs.md (default build/docs-srs)
    python3 docs/_sphinx/reqs.py trace [OUT]  # OUT/trace.csv: code/test files per ID (AUD-A4-01)
"""

from __future__ import annotations

import csv
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
SKIP_DIRS = ("archive/", "adr/", "_sphinx/", "_build/")
ID_RE = re.compile(r"^([A-Z]{2,4})-(\d{2})$")
CITE_RE = re.compile(r"\b([A-Z]{2,4})-(\d{2})\b")
PRI = {"M", "S", "C", "—"}

# Table kinds by exact header. Any other table whose first column is `ID` must not hold XXX-nn rows.
KINDS = {
    ("ID", "Requirement", "Pri"): "requirement",
    ("ID", "Requirement", "Pri", "Target"): "quality",
    ("ID", "Method & path", "Purpose", "Ref"): "interface",
    ("ID", "Layer", "Tooling", "Covers"): "verification",
    ("ID", "Gate", "Check", "Status"): "release",
}
SRS_KINDS = {"requirement", "quality", "interface", "verification"}


@dataclass
class Row:
    id: str
    owner: str  # path relative to docs/
    line: int
    kind: str
    header: tuple[str, ...]
    cells: list[str]

    @property
    def prefix(self) -> str:
        return self.id.split("-")[0]

    @property
    def pri(self) -> str:
        return self.cells[self.header.index("Pri")] if "Pri" in self.header else ""


@dataclass
class Owner:
    prefixes: list[str]
    path: str
    topic: str


@dataclass
class Model:
    owners: list[Owner] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_id(self) -> dict[str, Row]:
        return {r.id: r for r in self.rows}

    def owner_of(self, prefix: str) -> Owner | None:
        return next((o for o in self.owners if prefix in o.prefixes), None)


def split_cells(line: str) -> list[str]:
    """GFM cells: split on pipes not escaped with a backslash (also inside code spans)."""
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]


def md_files() -> list[Path]:
    out = []
    for p in sorted(DOCS.rglob("*.md")):
        rel = p.relative_to(DOCS).as_posix()
        if not rel.startswith(SKIP_DIRS):
            out.append(p)
    return out


def tables(text: str) -> Iterator[tuple[int, list[str]]]:
    """Yield (first_line_no, [lines]) for each run of table lines outside code fences."""
    block: list[str] = []
    start = 0
    fence = False
    for n, line in enumerate([*text.splitlines(), ""], 1):
        if line.lstrip().startswith("```"):
            fence = not fence
        if not fence and line.startswith("|"):
            if not block:
                start = n
            block.append(line)
            continue
        if block:
            yield start, block
            block = []


def parse_ownership(model: Model) -> None:
    text = (DOCS / "INDEX.md").read_text(encoding="utf-8")
    sec = text.split("## Ownership", 1)[-1].split("\n## ", 1)[0]
    for line in sec.splitlines():
        if not line.startswith("| `"):
            continue
        cells = split_cells(line)
        prefixes = re.findall(r"`([A-Z]{2,4})-`", cells[0])
        if prefixes and "," not in cells[1]:
            model.owners.append(Owner(prefixes, cells[1], cells[2]))


def parse() -> Model:
    model = Model()
    parse_ownership(model)
    seen: dict[str, str] = {}
    for p in md_files():
        rel = p.relative_to(DOCS).as_posix()
        for start, block in tables(p.read_text(encoding="utf-8")):
            header = tuple(split_cells(block[0]))
            first = split_cells(block[0])[0] if block else ""
            if ID_RE.match(first):
                model.errors.append(
                    f"{rel}:{start}: ID rows without a header (blank line in a table?)"
                )
                continue
            if header[:1] != ("ID",):
                continue
            kind = KINDS.get(header)
            for off, line in enumerate(block[2:], start + 2):
                cells = split_cells(line)
                if not cells or not ID_RE.match(cells[0]):
                    continue
                where = f"{rel}:{off}"
                if kind is None:
                    model.errors.append(f"{where}: {cells[0]} in a table with header {header}")
                    continue
                if len(cells) != len(header):
                    model.errors.append(
                        f"{where}: {cells[0]} has {len(cells)} cells, header {len(header)}"
                        " (unescaped `|`?)"
                    )
                    continue
                row = Row(cells[0], rel, off, kind, header, cells)
                if row.id in seen:
                    model.errors.append(f"{where}: duplicate ID {row.id} (first at {seen[row.id]})")
                    continue
                seen[row.id] = where
                owner = model.owner_of(row.prefix)
                if owner is None:
                    model.errors.append(f"{where}: prefix {row.prefix}- not in INDEX §Ownership")
                elif owner.path != rel:
                    model.errors.append(f"{where}: {row.id} defined outside its owner {owner.path}")
                if "Pri" in header and row.pri not in PRI:
                    model.errors.append(f"{where}: {row.id} Pri {row.pri!r} not in M/S/C/—")
                model.rows.append(row)
    check_citations(model)
    check_srs_directives(model)
    return model


def check_citations(model: Model) -> None:
    defined = model.by_id()
    known = {p for o in model.owners for p in o.prefixes}
    for p in md_files():
        rel = p.relative_to(DOCS).as_posix()
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for m in CITE_RE.finditer(line):
                rid = m.group(0)
                if m.group(1) in known and rid not in defined:
                    model.warnings.append(f"{rel}:{n}: {rid} cited but not defined")


SRS_DIRECTIVE = re.compile(r"^```\{srs-table\}\s+(.+)$", re.M)


def srs_groups() -> list[list[str]]:
    path = DOCS / "product" / "SRS.md"
    if not path.exists():
        return []
    return [m.group(1).split() for m in SRS_DIRECTIVE.finditer(path.read_text(encoding="utf-8"))]


def check_srs_directives(model: Model) -> None:
    groups = srs_groups()
    if not groups:
        return
    placed = Counter(p for g in groups for p in g)
    used = {r.prefix for r in model.rows if r.kind in SRS_KINDS}
    for pre in sorted(used):
        if placed[pre] != 1:
            model.errors.append(
                f"product/SRS.md: {pre}- in {placed[pre]} srs-table directives, need 1"
            )


# -- journeys (VISION §Journeys) -------------------------------------------------------------------


def journeys(model: Model) -> dict[str, list[str]]:
    """Map requirement ID -> journeys (G1..G4) from the Refs column of VISION §Journeys."""
    text = (DOCS / "product" / "VISION.md").read_text(encoding="utf-8")
    ids = [r.id for r in model.rows]
    out: dict[str, list[str]] = defaultdict(list)
    for _, block in tables(text):
        header = split_cells(block[0])
        if header[:1] != ["Path"] or header[-1] != "Refs":
            continue
        for line in block[2:]:
            cells = split_cells(line)
            g = re.search(r"\bG\d\b", cells[0])
            if not g:
                continue
            for ref in expand_refs(cells[-1], ids):
                out[ref].append(g.group(0))
    return out


def expand_refs(text: str, ids: list[str]) -> list[str]:
    refs: list[str] = []
    for tok in re.findall(r"[A-Z]{2,4}-(?:\*|\d{2}(?:/\d{2})*(?:\.\.\d{2})?)", text):
        pre, rest = tok.split("-", 1)
        if rest == "*":
            refs += [i for i in ids if i.startswith(pre + "-")]
        elif ".." in rest:
            a, b = rest.split("..")
            refs += [f"{pre}-{n:02d}" for n in range(int(a), int(b) + 1)]
        else:
            refs += [f"{pre}-{n}" for n in rest.split("/")]
    return refs


# -- trace (code / test citations, AUD-A4-01) ------------------------------------------------------

CODE_EXT = {".py", ".ts", ".tsx", ".sh", ".js", ".css", ".yml", ".yaml", ".toml"}
PRUNE = {
    "node_modules",
    "__pycache__",
    "dist",
    ".venv",
    "test-results",
    ".pytest_cache",
    "playwright-report",
}


def is_test(rel: str) -> bool:
    return (
        rel.startswith(("backend/tests/", "frontend/e2e/"))
        or re.search(r"\.test\.(ts|tsx)$", rel) is not None
        or "/tests/" in rel
    )


def citations() -> tuple[Counter[str], Counter[str]]:
    """Count files citing each ID in code and in tests."""
    code: Counter[str] = Counter()
    test: Counter[str] = Counter()
    for base in ("backend", "frontend/src", "frontend/e2e", "plugins", "scripts"):
        for dp, dn, fn in os.walk(ROOT / base):
            dn[:] = [d for d in dn if d not in PRUNE]
            for f in fn:
                fp = Path(dp) / f
                if fp.suffix not in CODE_EXT or "openapi" in f:
                    continue
                rel = fp.relative_to(ROOT).as_posix()
                found = {m.group(0) for m in CITE_RE.finditer(fp.read_text(errors="ignore"))}
                (test if is_test(rel) else code).update(found)
    return code, test


# -- open audit findings (MVP REL-03; the v3 audit is closed and archived) -------------------------

FINDINGS = DOCS / "archive" / "v3" / "audit" / "findings"


def open_findings() -> Counter[str]:
    out: Counter[str] = Counter()
    for p in sorted(FINDINGS.glob("A*.md")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("| AUD-"):
                c = split_cells(line)
                dec = c[8] if len(c) > 8 else ""
                if not re.match(r"(fixed|defer|reject)\b", dec):
                    out[c[1]] += 1
    return out


# -- CLI -------------------------------------------------------------------------------------------


def report(model: Model) -> int:
    for w in model.warnings:
        print("warning:", w)
    for e in model.errors:
        print("error:", e)
    pri = Counter(r.pri or r.kind for r in model.rows)
    counts = " · ".join(f"{k} {v}" for k, v in sorted(pri.items()))
    print(f"reqs: {len(model.rows)} IDs · {counts}")
    print(f"reqs: {len(model.errors)} errors, {len(model.warnings)} warnings")
    return 1 if model.errors else 0


def write_srs(model: Model, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    jr = journeys(model)
    _, test = citations()
    with open(out / "srs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "kind", "pri", "owner", "line", "journeys", "tests", "text"])
        for r in model.rows:
            g = " ".join(jr.get(r.id, []))
            w.writerow([r.id, r.kind, r.pri, r.owner, r.line, g, test[r.id], r.cells[1]])
    lines = ["# SRS review table (generated; do not commit)", ""]
    for o in model.owners:
        rows = [r for r in model.rows if r.owner == o.path and r.kind in SRS_KINDS]
        if rows:
            lines += [f"## {o.topic} ({o.path})", "", "| ID | Pri | Journeys | Tests | Text |"]
            lines.append("|---|---|---|---|---|")
            for r in rows:
                g = " ".join(jr.get(r.id, []))
                lines.append(f"| {r.id} | {r.pri} | {g} | {test[r.id]} | {r.cells[1]} |")
            lines.append("")
    m = [r for r in model.rows if r.pri == "M"]
    of = open_findings()
    lines += [
        "## Counts",
        "",
        f"- M {len(m)} · behind a journey {sum(1 for r in m if r.id in jr)}"
        f" · without a test citing them {sum(1 for r in m if not test[r.id])}",
        f"- Open audit findings: P0 {of['P0']} · P1 {of['P1']} · P2 {of['P2']}",
    ]
    (out / "srs.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"reqs: wrote {out / 'srs.csv'} and {out / 'srs.md'}; open P0 {of['P0']}, P1 {of['P1']}")


def write_trace(model: Model, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    code, test = citations()
    with open(out / "trace.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "owner", "line", "pri", "code_files", "test_files"])
        for r in model.rows:
            w.writerow([r.id, r.owner, r.line, r.pri, code[r.id], test[r.id]])
    m = [r for r in model.rows if r.pri == "M"]
    no_code = [r.id for r in m if not code[r.id]]
    no_test = [r.id for r in m if not test[r.id]]
    print(f"trace: M {len(m)} · no code citation {len(no_code)} · no test citation {len(no_test)}")
    print("trace: M without code or test:", " ".join(i for i in no_code if i in no_test) or "none")
    print(f"trace: wrote {out / 'trace.csv'} (a report, not a gate)")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    model = parse()
    status = report(model)
    if cmd == "check":
        return status
    default = ROOT / "build" / ("docs-srs" if cmd == "srs" else "trace")
    out = Path(argv[2]) if len(argv) > 2 else default
    if cmd == "srs":
        write_srs(model, out)
    elif cmd == "trace":
        write_trace(model, out)
    else:
        print(__doc__)
        return 2
    return status


# -- Sphinx extension ------------------------------------------------------------------------------

PATH_RE = re.compile(r"^(?:[\w.-]+/)*[\w.-]+\.md$")
TEXT_RE = re.compile(r"\b([A-Z]{2,4}-\d{2}|ADR-\d{4})\b|\b([A-Z][A-Z_]{2,})(?:\.md\b| (?=§))")


def setup(app):  # type: ignore[no-untyped-def]
    from docutils import nodes
    from docutils.statemachine import StringList
    from sphinx.util import logging
    from sphinx.util.docutils import SphinxDirective

    model = parse()
    for e in model.errors:  # fail `sphinx-build -W` on the same errors as `make check`
        logging.getLogger(__name__).warning("reqs: %s", e)
    rows = model.by_id()
    jr = journeys(model)
    _, test = citations()

    class SrsTable(SphinxDirective):
        """```{srs-table} PRJ IMP ...``` renders those prefixes' rows, grouped by owner doc."""

        required_arguments = 1
        optional_arguments = 40
        has_content = False

        def run(self):  # type: ignore[no-untyped-def]
            want = set(self.arguments)
            md: list[str] = []
            for o in model.owners:
                group = [
                    r
                    for r in model.rows
                    if r.owner == o.path and r.prefix in want and r.kind in SRS_KINDS
                ]
                if not group:
                    continue
                rel = os.path.relpath(o.path, os.path.dirname(self.env.docname))
                md += [f"**{o.topic}** · [{Path(o.path).stem}]({rel})", ""]
                extra = ("Journeys", "Tests") if group[0].kind in ("requirement", "quality") else ()
                header = group[0].header + extra
                md += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
                for r in group:
                    cells = list(r.cells)
                    if extra:
                        n = str(test[r.id]) if test[r.id] else "—"
                        cells += [" ".join(jr.get(r.id, [])), n]
                    md.append("| " + " | ".join(cells) + " |")
                md.append("")
            box = nodes.container(classes=["srs"])
            lines = StringList(md, source=self.env.docname)
            self.state.nested_parse(lines, self.content_offset, box)
            for row in box.findall(nodes.row):
                rid = row.astext().split()[0] if row.astext().strip() else ""
                if rid in rows:
                    row["ids"].append("req-" + rid.lower())
                    row[0]["classes"].append("srs-id")
            return [box]

    def resolve_doc(env, docname: str, target: str) -> str | None:  # type: ignore[no-untyped-def]
        t = target[:-3] if target.endswith(".md") else target
        t = t.removeprefix("docs/")
        cands = [os.path.normpath(os.path.join(os.path.dirname(docname), t)), t]
        cands += [d for d in env.found_docs if d.rsplit("/", 1)[-1] == Path(t).name]
        hits = [c for c in dict.fromkeys(cands) if c in env.found_docs]
        return hits[0] if hits and (len(hits) == 1 or hits[0] in cands[:2]) else None

    def adr_doc(env, num: str) -> str | None:  # type: ignore[no-untyped-def]
        return next((d for d in sorted(env.found_docs) if d.startswith(f"adr/{num}-")), None)

    def link(app, doctree, docname):  # type: ignore[no-untyped-def]
        env, builder = app.env, app.builder
        if not hasattr(builder, "get_relative_uri"):
            return

        def ref(target: str, anchor: str, child):  # type: ignore[no-untyped-def]
            uri = builder.get_relative_uri(docname, target) + (f"#{anchor}" if anchor else "")
            r = nodes.reference("", "", internal=True, refuri=uri, classes=["xref-auto"])
            r += child
            return r

        skip = (nodes.reference, nodes.title, nodes.raw, nodes.FixedTextElement, nodes.literal)
        for lit in list(doctree.findall(nodes.literal)):
            txt = lit.astext()
            if PATH_RE.match(txt) and not isinstance(lit.parent, nodes.reference):
                doc = resolve_doc(env, docname, txt)
                if doc:
                    lit.replace_self(ref(doc, "", lit.deepcopy()))
        for tn in list(doctree.findall(nodes.Text)):
            par = tn.parent
            ups = list(_ancestors(tn))
            if par is None or any(isinstance(a, skip) for a in ups):
                continue
            if any("srs-id" in a.get("classes", []) for a in ups if isinstance(a, nodes.Element)):
                continue
            s = str(tn)
            out, pos = [], 0
            for m in TEXT_RE.finditer(s):
                target, anchor = None, ""
                if m.group(1) and m.group(1).startswith("ADR-"):
                    target = adr_doc(env, m.group(1)[4:])
                    anchor = ""
                elif m.group(1) and m.group(1) in rows and rows[m.group(1)].kind in SRS_KINDS:
                    target, anchor = "product/SRS", "req-" + m.group(1).lower()
                elif m.group(2):
                    target, anchor = resolve_doc(env, docname, m.group(2)), ""
                if not target or (target == docname and not anchor):
                    continue
                out.append(nodes.Text(s[pos : m.start()]))
                out.append(ref(target, anchor, nodes.Text(m.group(0))))
                pos = m.end()
            if out:
                out.append(nodes.Text(s[pos:]))
                par.replace(tn, out)

    app.add_directive("srs-table", SrsTable)
    app.connect("doctree-resolved", link)
    return {"parallel_read_safe": True, "parallel_write_safe": True}


def _ancestors(node: Any) -> Iterator[Any]:
    n = node.parent
    while n is not None:
        yield n
        n = n.parent


if __name__ == "__main__":
    sys.exit(main(sys.argv))
