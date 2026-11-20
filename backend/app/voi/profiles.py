"""Sampling profiles of a `voi.extract` run: recomputed from its catalog with other settings (no
volume is read) and saved as named variants in the project (`tasks/runs/{rid}/profiles/`)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from app.core.errors import NotFound, ValidationProblem
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import utc_now
from app.voi.catalog import load
from app.voi.models import VoiProfile, VoiProfileSettings, VoiProfileSummary

if TYPE_CHECKING:
    from types import ModuleType

PROFILES: Final = "profiles"
RUN_PROFILE: Final = "sampling_profile.json"  # the one the run wrote, with its own settings
NAME_RE: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
RUN: Final = "run"  # the name that downloads the run's own profile


def _profile() -> ModuleType:
    from plugins.voi import profile

    return profile


def compute(
    output_dir: Path, run_settings: dict[str, Any], change: VoiProfileSettings
) -> VoiProfile:
    pm = _profile()
    rows = pm.latest_rows(load(output_dir))
    lesions = pm.lesion_rows(rows)
    settings = {**run_settings, **change.model_dump(exclude_none=True)}
    try:
        prof, _ = pm.build_profile(lesions, settings, pm.shared_spacing(rows))
    except ValueError as exc:
        raise ValidationProblem(str(exc), errors=[{"loc": ["body"], "msg": str(exc)}]) from None
    return VoiProfile(profile=prof, lesion_volumes_mm3=[float(x["volume_mm3"]) for x in lesions])


def _dir(run_dir: Path) -> Path:
    return run_dir / PROFILES


def _name(name: str) -> str:
    if not NAME_RE.match(name) or name == RUN:
        raise ValidationProblem(
            f"Profile name {name!r}: lower-case letters, digits, - or _ (not {RUN!r})",
            errors=[{"loc": ["path", "name"], "msg": "invalid profile name"}],
        )
    return name


def save(run_dir: Path, name: str, computed: VoiProfile, by: str | None) -> VoiProfile:
    saved = VoiProfile(name=_name(name), saved_at=utc_now(), saved_by=by, profile=computed.profile)
    atomic_write_json(_dir(run_dir) / f"{name}.json", saved.model_dump(mode="json"))
    return saved


def saved(run_dir: Path) -> list[VoiProfileSummary]:
    d = _dir(run_dir)
    out: list[VoiProfileSummary] = []
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        p = VoiProfile.model_validate(read_json(f))
        out.append(
            VoiProfileSummary(
                name=str(p.name),
                saved_at=str(p.saved_at),
                saved_by=p.saved_by,
                settings_hash=str(p.profile.get("settings_hash", "")),
                num_lesions=int(p.profile.get("num_lesions", 0)),
            )
        )
    return out


def export(run_dir: Path, output_dir: Path, name: str) -> dict[str, Any]:
    """The profile a sampler reads: the run's own (`run`) or a saved variant."""
    if name == RUN:
        path = output_dir / RUN_PROFILE
        if not path.is_file():
            raise NotFound("the run wrote no sampling profile")
        return dict(read_json(path))
    path = _dir(run_dir) / f"{_name(name)}.json"
    if not path.is_file():
        raise NotFound(f"Profile {name!r} not found")
    return dict(VoiProfile.model_validate(read_json(path)).profile)
