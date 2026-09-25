"""Server-path and project-id redaction (NFR-17, PRJ-17, PRJ-08).

`Redactor` rewrites strings so that no absolute server path and no real `project_id` leaves:
a path under a project root becomes its alias ref (`/data/ds/nifti/a.nii.gz` →
`DATA:nifti/a.nii.gz`), a path under any other known server folder (workspace, allowed roots)
loses that prefix (`…/rest`), and the project id is replaced by a stand-in. Used by the
view-only mirror (API-60) and by bundle export (PROJECT_FORMAT §Bundles).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from typing import Any

ELIDED = "…"
_END = r"(?=[\s\"'`),;:\]}]|$)"  # a bare root ends here (else `/data/ds` would match `/data/ds2`)


def _variants(path: str) -> set[str]:
    p = path.rstrip("/")
    out = {p} if p else set()
    try:
        real = os.path.realpath(p).rstrip("/")
    except (OSError, ValueError):
        real = ""
    if real:
        out.add(real)
    return {v for v in out if len(v) > 1}  # never the bare `/`


class Redactor:
    def __init__(
        self,
        aliases: Iterable[tuple[str, str]] = (),
        folders: Iterable[str] = (),
        ids: Iterable[tuple[str, str]] = (),
    ) -> None:
        """`aliases`: (alias, absolute root); `folders`: other absolute server folders;
        `ids`: (real id, stand-in) substring replacements."""
        rules: dict[str, tuple[str, str]] = {}  # prefix → (followed by `/`, bare)
        for folder in folders:
            for v in _variants(folder):
                rules[v] = (ELIDED + "/", ELIDED)
        for alias, root in aliases:
            for v in _variants(root):
                rules[v] = (f"{alias}:", f"{alias}:")
        # Longest prefix first, so a project root wins over the allowed root that contains it.
        self._paths = [
            (prefix, re.compile(re.escape(prefix) + _END), slash, bare)
            for prefix, (slash, bare) in sorted(rules.items(), key=lambda kv: -len(kv[0]))
        ]
        self._ids = [(a, b) for a, b in ids if a]

    def text(self, s: str) -> str:
        for prefix, pattern, slash, bare in self._paths:
            if prefix in s:
                s = pattern.sub(bare, s.replace(prefix + "/", slash))  # aliases need no escaping
        for real, stand_in in self._ids:
            if real in s:
                s = s.replace(real, stand_in)
        return s

    def value(self, v: Any) -> Any:
        """A JSON-like value with every string (and dict key) redacted."""
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, dict):
            return {self.text(k) if isinstance(k, str) else k: self.value(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self.value(x) for x in v]
        return v

    def json_bytes(self, data: bytes) -> bytes:
        try:
            obj = json.loads(data)
        except ValueError:
            return self.text(data.decode("utf-8", "replace")).encode("utf-8")
        return json.dumps(self.value(obj), ensure_ascii=False, separators=(",", ":")).encode()

    def jsonl_bytes(self, data: bytes) -> bytes:
        out: list[str] = []
        for line in data.decode("utf-8", "replace").splitlines(keepends=True):
            body = line.rstrip("\r\n")
            end = line[len(body) :]
            if not body.strip():
                out.append(line)
                continue
            try:
                obj = json.loads(body)
            except ValueError:
                out.append(self.text(body) + end)
                continue
            out.append(json.dumps(self.value(obj), ensure_ascii=False) + end)
        return "".join(out).encode("utf-8")

    def sse_bytes(self, data: bytes) -> bytes:
        """One SSE chunk: `data:` lines are JSON-redacted, the other lines are text."""
        out: list[str] = []
        for line in data.decode("utf-8", "replace").splitlines(keepends=True):
            body = line.rstrip("\r\n")
            end = line[len(body) :]
            if body.startswith("data:"):
                payload = body[5:].lstrip(" ")
                try:
                    red = json.dumps(self.value(json.loads(payload)), ensure_ascii=False)
                except ValueError:
                    red = self.text(payload)
                out.append(f"data: {red}{end}")
            else:
                out.append(self.text(body) + end)
        return "".join(out).encode("utf-8")
