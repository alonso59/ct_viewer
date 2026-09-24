"""Path aliases and guards (BE-02, PRJ-04, PROJECT_FORMAT.md §Path aliases).

Every access to referenced data goes through `PathResolver.resolve(ref)`: the real path
(symlinks followed) must stay inside the alias root **and** inside `ALLOWED_DATA_ROOTS`
(`source` roots) or `ALLOWED_DERIVED_ROOTS` (`derived` roots, ADR-0014, OPS-12).
Source files are opened read-only through `open_source` (BE-03, R1).
"""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from app.core.errors import NotFound, PathOutsideRoot, ValidationProblem

ALIAS_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,15}$")


@dataclass(frozen=True)
class AliasRef:
    alias: str
    rel: str

    def __str__(self) -> str:
        return f"{self.alias}:{self.rel}"


def validate_alias(alias: str) -> str:
    if not ALIAS_RE.match(alias):
        raise ValidationProblem(
            f"Invalid alias {alias!r}",
            errors=[{"loc": ["alias"], "msg": "must match [A-Z][A-Z0-9_]{0,15}"}],
        )
    return alias


def validate_rel(rel: str) -> str:
    """A ref's relative part: POSIX, relative, normalized, no `..` (PROJECT_FORMAT.md)."""
    if not rel or "\\" in rel or "\x00" in rel or rel.startswith("/"):
        raise ValidationProblem(f"Invalid relative path {rel!r}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValidationProblem(f"Relative path must be normalized without '..': {rel!r}")
    return rel


def parse_ref(ref: str) -> AliasRef:
    alias, sep, rel = ref.partition(":")
    if not sep:
        raise ValidationProblem(f"Not an alias ref: {ref!r}")
    return AliasRef(validate_alias(alias), validate_rel(rel))


def make_ref(alias: str, rel: str) -> str:
    return str(AliasRef(validate_alias(alias), validate_rel(rel)))


def is_within(path: Path, root: Path) -> bool:
    """Both arguments must already be resolved (realpath)."""
    return path == root or root in path.parents


def realpath(path: Path | str) -> Path:
    return Path(os.path.realpath(path))


class PathGuard:
    """`ALLOWED_DATA_ROOTS` containment (OPS-04). An empty list is unrestricted (dev only).

    `strict=True` (the derived guard, OPS-11): an empty list allows nothing.
    """

    def __init__(
        self,
        allowed_roots: Sequence[Path],
        *,
        name: str = "ALLOWED_DATA_ROOTS",
        strict: bool = False,
    ) -> None:
        self.allowed_roots = [realpath(p) for p in allowed_roots]
        self.name = name
        self.strict = strict

    @property
    def restricted(self) -> bool:
        return bool(self.allowed_roots) or self.strict

    def is_allowed(self, path: Path) -> bool:
        real = realpath(path)
        return not self.restricted or any(is_within(real, r) for r in self.allowed_roots)

    def check(self, path: Path) -> Path:
        """Return the real path, or raise `path-outside-root`."""
        real = realpath(path)
        if self.restricted and not any(is_within(real, r) for r in self.allowed_roots):
            raise PathOutsideRoot(f"Path is outside {self.name}")
        return real


RootRole = Literal["source", "derived"]


class PathResolver:
    """Resolve `ALIAS:rel` refs for one project (BE-02); `derived` aliases use `derived_guard`."""

    def __init__(
        self,
        roots: Mapping[str, Path | str],
        guard: PathGuard,
        *,
        roles: Mapping[str, RootRole] | None = None,
        derived_guard: PathGuard | None = None,
    ) -> None:
        self.roots = {a: Path(p) for a, p in roots.items()}
        self.guard = guard
        self.roles: dict[str, RootRole] = dict(roles or {})
        self.derived_guard = derived_guard or PathGuard(
            [], name="ALLOWED_DERIVED_ROOTS", strict=True
        )

    def role(self, alias: str) -> RootRole:
        return self.roles.get(alias, "source")

    def guard_for(self, alias: str) -> PathGuard:
        return self.derived_guard if self.role(alias) == "derived" else self.guard

    def root(self, alias: str) -> Path:
        try:
            return self.roots[alias]
        except KeyError:
            raise NotFound(f"Unknown alias {alias!r}") from None

    def resolve(self, ref: str) -> Path:
        r = parse_ref(ref)
        root_real = realpath(self.root(r.alias))
        cand = realpath(root_real / r.rel)
        if not is_within(cand, root_real):
            raise PathOutsideRoot(f"{r.alias}: path escapes its alias root")
        return self.guard_for(r.alias).check(cand)

    def to_ref(self, alias: str, raw: str) -> str:
        """Turn an input path (relative to the alias root, or absolute legacy) into a ref.

        Lexical normalization only; `..` escapes or absolute paths outside the root raise
        `path-outside-root`. Symlink escapes are caught later by `resolve`.
        """
        root = self.root(alias)
        raw = raw.strip().replace("\\", "/")
        if not raw:
            raise ValidationProblem("Empty path")
        if raw.startswith("/"):
            root_norm = posixpath.normpath(root.as_posix())
            norm = posixpath.normpath(raw)
            if not (norm + "/").startswith(root_norm.rstrip("/") + "/"):
                raise PathOutsideRoot("Absolute path outside its alias root")
            rel = posixpath.relpath(norm, root_norm)
        else:
            rel = posixpath.normpath(raw)
        if rel in (".", "") or rel == ".." or rel.startswith("../"):
            raise PathOutsideRoot("Relative path escapes its alias root")
        return make_ref(alias, rel)


def open_source(path: Path) -> BinaryIO:
    """The only way services open referenced source files: read-only binary (BE-03, R1)."""
    return path.open("rb")
