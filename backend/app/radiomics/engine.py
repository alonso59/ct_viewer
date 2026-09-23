"""Radiomics engine adapter (RAD-12, ADR-0006).

The protocol is the only thing services and the UI depend on; the default engine is
PyRadiomics (`pyradiomics_engine`), an optional extra (`[radiomics]`). It is imported lazily,
so the app imports and starts without it; engine-dependent endpoints then answer
503 `server-busy` (`EngineUnavailable`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.errors import ServerBusy
from app.radiomics.models import Issue, SettingsSchema

DEFAULT_ENGINE = "pyradiomics"


@dataclass(frozen=True)
class FeatureValue:
    image_type: str
    feature_class: str
    feature: str
    value: float


@dataclass
class ExtractionResult:
    features: list[FeatureValue]
    diagnostics: dict[str, Any] = field(default_factory=dict)  # flattened, JSON scalars


class RadiomicsEngine(Protocol):
    name: str
    version: str

    def schema(self) -> SettingsSchema:
        """Options, defaults, constraints, filters, feature classes, IBSI metadata (RAD-01)."""
        ...

    def validate(self, settings: dict[str, Any]) -> list[Issue]:
        """All issues for a `RadiomicsSettings`-shaped dict: schema checks + rules (RAD-04)."""
        ...

    def extract(
        self, image_path: str, mask_path: str, label: int, settings: dict[str, Any]
    ) -> ExtractionResult:
        """One (image, mask, label) extraction with *normalized* settings. Opens files `rb`."""
        ...

    def dependency_versions(self) -> dict[str, str]: ...


class EngineUnavailable(ServerBusy):
    """The engine (optional extra) is not installed in this environment."""


_ENGINES: dict[str, RadiomicsEngine] = {}


def get_engine(name: str = DEFAULT_ENGINE) -> RadiomicsEngine:
    """The (cached) engine instance; raises `EngineUnavailable` when it cannot be imported."""
    eng = _ENGINES.get(name)
    if eng is not None:
        return eng
    if name != DEFAULT_ENGINE:
        raise EngineUnavailable(f"Unknown radiomics engine {name!r}")
    try:
        from app.radiomics.pyradiomics_engine import PyRadiomicsEngine

        eng = PyRadiomicsEngine()
    except ImportError as exc:
        raise EngineUnavailable(
            f"Radiomics engine not installed ({exc.name or exc}); install the [radiomics] extra"
        ) from None
    _ENGINES[name] = eng
    return eng
