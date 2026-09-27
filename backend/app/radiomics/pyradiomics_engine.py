"""PyRadiomics adapter (RAD-12, ADR-0006). Import this module only through `engine.get_engine`.

The schema is introspected from the installed engine: option names, types and constraints
from its parameter schema (`paramSchema.yaml` + `schemaFuncs.py` enums), defaults from
`RadiomicsFeatureExtractor._getDefaultSettings()` over `CODE_DEFAULTS` (defaults PyRadiomics
only declares inline via `kwargs.get(name, default)`; a test checks them against the engine
source), filters from `getImageTypes()` and features from each class's `getFeatureNames()`.
"""

from __future__ import annotations

import importlib
import json
import logging
import math
import platform
import threading
from functools import cached_property
from typing import Any

import numpy as np
import radiomics
from radiomics import featureextractor

from app.radiomics import ibsi
from app.radiomics import settings as st
from app.radiomics.engine import ExtractionResult, FeatureValue
from app.radiomics.models import (
    Constraints,
    EngineInfo,
    FeatureClassSpec,
    FeatureSpec,
    FilterSpec,
    GroupSpec,
    Issue,
    OptionSpec,
    OptionType,
    RadiomicsSettings,
    SettingsSchema,
)

# PyRadiomics is not thread-safe (settings loader, module-level logging and C-extension state).
# Worker processes run one unit at a time; inline (threaded) jobs, as in the tests, share one
# process, so extraction is serialized here.
_EXTRACT_LOCK = threading.Lock()

log = logging.getLogger("app.radiomics")

GROUPS: list[tuple[str, str]] = [
    ("filters", "Filters"),
    ("feature_classes", "Feature classes"),
    ("discretization", "Discretization"),
    ("resampling", "Resampling"),
    ("intensity", "Intensity"),
    ("resegmentation", "Re-segmentation"),
    ("mask", "Mask handling"),
    ("two_d", "2D"),
    ("texture", "Texture"),
    ("output", "Output"),
    ("other", "Other"),
]
OPTION_GROUP: dict[str, str] = {
    "binWidth": "discretization",
    "binCount": "discretization",
    "resampledPixelSpacing": "resampling",
    "interpolator": "resampling",
    "padDistance": "resampling",
    "preCrop": "resampling",
    "normalize": "intensity",
    "normalizeScale": "intensity",
    "removeOutliers": "intensity",
    "voxelArrayShift": "intensity",
    "resegmentRange": "resegmentation",
    "resegmentMode": "resegmentation",
    "resegmentShape": "resegmentation",
    "minimumROIDimensions": "mask",
    "minimumROISize": "mask",
    "geometryTolerance": "mask",
    "correctMask": "mask",
    "label_channel": "mask",
    "force2D": "two_d",
    "force2Ddimension": "two_d",
    "distances": "texture",
    "symmetricalGLCM": "texture",
    "weightingNorm": "texture",
    "gldm_a": "texture",
    "additionalInfo": "output",
}
FILTER_PARAMS: dict[str, list[str]] = {
    "LoG": ["sigma"],
    "Wavelet": ["wavelet", "start_level", "level"],
    "Gradient": ["gradientUseSpacing"],
    "LBP2D": ["lbp2DRadius", "lbp2DSamples", "lbp2DMethod"],
    "LBP3D": ["lbp3DLevels", "lbp3DIcosphereRadius", "lbp3DIcosphereSubdivision"],
}
# Chosen per extraction from the selection (RAD-05), not a form option.
EXCLUDED_OPTIONS: frozenset[str] = frozenset({"label"})
# Defaults PyRadiomics declares only inline (`kwargs.get(name, default)`); verified by a test.
CODE_DEFAULTS: dict[str, Any] = {
    "binWidth": 25.0,
    "binCount": None,
    "geometryTolerance": None,
    "correctMask": False,
    "label_channel": 0,
    "resegmentMode": "absolute",
    "resegmentShape": False,
    "voxelArrayShift": 0,
    "symmetricalGLCM": True,
    "weightingNorm": None,
    "gldm_a": 0,
    "sigma": [],
    "wavelet": "coif1",
    "start_level": 0,
    "level": 1,
    "gradientUseSpacing": True,
    "lbp2DRadius": 1.0,
    "lbp2DSamples": 8,
    "lbp2DMethod": "uniform",
    "lbp3DLevels": 2,
    "lbp3DIcosphereRadius": 1.0,
    "lbp3DIcosphereSubdivision": 1,
}
# List-length constraints PyRadiomics checks at run time rather than in its schema.
ITEMS: dict[str, tuple[int | None, int | None]] = {
    "resampledPixelSpacing": (3, 3),
    "resegmentRange": (1, 2),
    "distances": (1, None),
}
INTERPOLATORS = [
    "sitkNearestNeighbor",
    "sitkLinear",
    "sitkBSpline",
    "sitkGaussian",
    "sitkLabelGaussian",
    "sitkHammingWindowedSinc",
    "sitkCosineWindowedSinc",
    "sitkWelchWindowedSinc",
    "sitkLanczosWindowedSinc",
    "sitkBlackmanWindowedSinc",
]
WEIGHTING = ["euclidean", "manhattan", "infinity", "no_weighting"]
DESCRIPTIONS: dict[str, str] = {
    "binWidth": "Fixed bin width (intensity units)",
    "binCount": "Fixed number of bins",
    "resampledPixelSpacing": "Target spacing [x, y, z] in mm; 0 keeps that axis",
    "interpolator": "Image interpolator used for resampling",
    "padDistance": "Voxels kept around the ROI when cropping before resampling",
    "preCrop": "Crop to the ROI before resampling",
    "normalize": "Normalize intensities (z-score) before extraction",
    "normalizeScale": "Scale applied after normalization",
    "removeOutliers": "Remove intensities beyond n standard deviations after normalization",
    "voxelArrayShift": "Shift added to intensities for first-order energy features",
    "resegmentRange": "Intensity range kept in the ROI [min, max]",
    "resegmentMode": "How the range is interpreted",
    "resegmentShape": "Also use the re-segmented ROI for shape features",
    "minimumROIDimensions": "Minimum number of dimensions the ROI must span",
    "minimumROISize": "Minimum number of ROI voxels",
    "geometryTolerance": "Tolerance when image and mask geometry differ",
    "correctMask": "Resample the mask onto the image grid when geometry differs",
    "label_channel": "Channel of a vector-valued mask",
    "force2D": "Extract texture per slice (2D)",
    "force2Ddimension": "Axis treated as out-of-plane in 2D mode",
    "distances": "Neighbour distances for texture matrices",
    "symmetricalGLCM": "Count co-occurrences in both directions",
    "weightingNorm": "Distance weighting of GLCM directions",
    "gldm_a": "Dependence threshold for GLDM",
    "additionalInfo": "Record diagnostics (versions, hashes, ROI geometry)",
    "sigma": "Gaussian sigma values in mm",
    "wavelet": "Wavelet family",
    "start_level": "First decomposition level",
    "level": "Number of decomposition levels",
    "gradientUseSpacing": "Use image spacing for the gradient",
    "lbp2DRadius": "LBP radius (mm)",
    "lbp2DSamples": "LBP sample points",
    "lbp2DMethod": "LBP method",
    "lbp3DLevels": "Spherical harmonics levels",
    "lbp3DIcosphereRadius": "Icosphere radius (mm)",
    "lbp3DIcosphereSubdivision": "Icosphere subdivisions",
}
# Validation messages (RADIOMICS.md §Validation rules)
MSG_BINS = "Choose bin width or bin count"
MSG_SIGMA = "LoG needs at least one sigma"
MSG_2D = "Enable 2D mode for this option"
MSG_SPACING = "Spacing must be positive"
MSG_RESEG_ORDER = "Minimum must be less than maximum"
MSG_RESEG_SIGMA = "Sigma mode needs one positive value"
MSG_NOTHING = "Nothing to extract"
MSG_NORMALIZE_HU = "HU range will be applied after normalization"
MESSAGES: dict[str, str] = {"resampledPixelSpacing": MSG_SPACING, "sigma": MSG_SIGMA}


def _load_param_schema() -> dict[str, Any]:
    schema_file, _ = radiomics.getParameterValidationFiles()
    yaml_mod: Any = importlib.import_module("ruamel.yaml")
    with open(schema_file, "rb") as fh:
        data: dict[str, Any] = yaml_mod.YAML(typ="safe", pure=True).load(fh)
    mapping: dict[str, Any] = data["mapping"]["setting"]["mapping"]
    return mapping


def _wavelets() -> list[str]:
    pywt: Any = importlib.import_module("pywt")
    return [str(w) for w in pywt.wavelist(kind="discrete")]


def _constraints(rule: dict[str, Any]) -> Constraints:
    rng = rule.get("range") or {}
    c = Constraints()
    if "min" in rng:
        c.min = float(rng["min"])
    if "min-ex" in rng:
        c.min, c.exclusive_min = float(rng["min-ex"]), True
    if "max" in rng:
        c.max = float(rng["max"])
    if "max-ex" in rng:
        c.max, c.exclusive_max = float(rng["max-ex"]), True
    if "enum" in rule:
        c.enum = [str(e) for e in rule["enum"]]
    return c


def _option(name: str, rule: dict[str, Any], defaults: dict[str, Any], group: str) -> OptionSpec:
    default = defaults.get(name)
    otype: OptionType
    if "seq" in rule:
        item = rule["seq"][0]
        otype = "int_list" if item.get("type") == "int" else "float_list"
        cons = _constraints(item)
        lo, hi = ITEMS.get(name, (None, None))
        cons.min_items, cons.max_items = lo, hi
    else:
        cons = _constraints(rule)
        func = rule.get("func")
        t = rule.get("type")
        if func == "checkInterpolator":
            otype, cons.enum = "enum", list(INTERPOLATORS)
        elif func == "checkWavelet":
            otype, cons.enum = "enum", _wavelets()
        elif func == "checkWeighting":
            otype, cons.enum = "enum", list(WEIGHTING)
        elif cons.enum is not None:
            otype = "enum"
        elif t in ("int", "float", "bool", "str"):
            otype = t
        else:
            otype = "str"
    if otype == "float" and isinstance(default, int) and not isinstance(default, bool):
        default = float(default)
    if otype == "float_list" and isinstance(default, list):
        default = [float(x) for x in default]
    return OptionSpec(
        name=name,
        group=group,
        type=otype,
        default=default,
        nullable=default is None or name in ("binWidth", "binCount"),
        constraints=cons,
        description=DESCRIPTIONS.get(name, ""),
    )


def _lbp3d_missing() -> str | None:
    try:
        importlib.import_module("trimesh.creation")
        special: Any = importlib.import_module("scipy.special")
        _ = special.sph_harm
    except (ImportError, AttributeError) as exc:
        return f"needs optional packages scipy.special.sph_harm and trimesh ({exc})"
    return None


def _lbp2d_missing() -> str | None:
    try:
        importlib.import_module("skimage.feature")
    except ImportError as exc:
        return f"needs scikit-image ({exc})"
    return None


def _jsonable(v: Any) -> Any:
    if isinstance(v, np.generic):
        v = v.item()
    if v is None or isinstance(v, bool | int | str):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple | np.ndarray):
        return [_jsonable(x) for x in (v.tolist() if isinstance(v, np.ndarray) else v)]
    return str(v)


def _real(value: Any) -> float:
    """Feature value as float64. Axis lengths come back as complex with a zero imaginary part."""
    try:
        x = complex(np.asarray(value).reshape(-1)[0])
    except (TypeError, ValueError, IndexError):
        return float("nan")
    return x.real if abs(x.imag) <= 1e-12 * max(1.0, abs(x.real)) else float("nan")


def flatten_diagnostics(raw: dict[str, Any]) -> dict[str, Any]:
    """`diagnostics_{Group}_{Name}` → `{Group}_{Name}` with JSON scalars (containers as JSON)."""
    out: dict[str, Any] = {}
    for key, value in raw.items():
        name = key[len("diagnostics_") :]
        v = _jsonable(value)
        out[name] = json.dumps(v, sort_keys=True) if isinstance(v, dict | list) else v
    return out


class PyRadiomicsEngine:
    """`RadiomicsEngine` over PyRadiomics (+ SimpleITK, PyWavelets)."""

    name = "pyradiomics"

    def __init__(self) -> None:
        self.version = str(radiomics.__version__)
        self._local = threading.local()
        for lg in ("radiomics", "pykwalify"):
            logging.getLogger(lg).setLevel(logging.ERROR)  # BE-09: no paths at info

    # -- schema (API-30) --------------------------------------------------------------------

    def defaults(self) -> dict[str, Any]:
        engine_defaults: dict[str, Any] = featureextractor.RadiomicsFeatureExtractor.__dict__[
            "_getDefaultSettings"
        ].__func__()
        return {**CODE_DEFAULTS, **engine_defaults}

    @cached_property
    def _schema(self) -> SettingsSchema:
        rules = _load_param_schema()
        defaults = self.defaults()
        filter_param_names = {p for ps in FILTER_PARAMS.values() for p in ps}
        options = [
            _option(n, r, defaults, OPTION_GROUP.get(n, "other"))
            for n, r in rules.items()
            if n not in EXCLUDED_OPTIONS and n not in filter_param_names
        ]
        missing = {"LBP2D": _lbp2d_missing(), "LBP3D": _lbp3d_missing()}
        filters = []
        for name in radiomics.getImageTypes():
            names = FILTER_PARAMS.get(name, [])
            params = [_option(p, rules[p], defaults, "filters") for p in names]
            reason = missing.get(name)
            filters.append(
                FilterSpec(
                    name=name,
                    default_enabled=name == "Original",
                    available=reason is None,
                    unavailable_reason=reason,
                    requires_2d=name == "LBP2D",
                    params=params,
                )
            )
        classes = []
        for cname, cls in radiomics.getFeatureClasses().items():
            feats = [
                FeatureSpec(
                    name=f,
                    default_enabled=not dep,
                    deprecated=bool(dep),
                    ibsi=ibsi.lookup(cname, f),
                )
                for f, dep in sorted(cls.getFeatureNames().items())
            ]
            classes.append(
                FeatureClassSpec(
                    name=cname,
                    default_enabled=cname != "shape2D",
                    requires_2d=cname == "shape2D",
                    features=feats,
                )
            )
        schema = SettingsSchema(
            engine=EngineInfo(name=self.name, version=self.version),
            ibsi_map_version=ibsi.map_version(),
            groups=[GroupSpec(id=i, label=lbl) for i, lbl in GROUPS],
            options=options,
            filters=filters,
            feature_classes=classes,
            defaults=RadiomicsSettings(),
        )
        norm, issues = st.normalize(schema, RadiomicsSettings(), MESSAGES)
        if norm is None:  # engine defaults must always be valid
            raise RuntimeError(f"engine defaults do not validate: {issues}")
        schema.defaults = norm
        return schema

    def schema(self) -> SettingsSchema:
        return self._schema.model_copy(deep=True)

    # -- validation (API-43, RAD-04) --------------------------------------------------------

    def validate(self, settings: dict[str, Any]) -> list[Issue]:
        raw = RadiomicsSettings.model_validate(settings)
        norm, issues = st.normalize(self._schema, raw, MESSAGES)
        if norm is not None:
            issues += rules(norm)
        return issues

    # -- extraction (worker process) --------------------------------------------------------

    def _extractor(self, settings: dict[str, Any]) -> Any:
        key = st.canonical_json(settings)
        cache: dict[str, Any] = getattr(self._local, "cache", None) or {}
        ext = cache.get(key)
        if ext is None:
            norm = RadiomicsSettings.model_validate(settings)
            params = {
                "setting": {k: v for k, v in (norm.settings or {}).items() if v is not None},
                "imageType": {
                    n: {k: v for k, v in p.items() if v is not None}
                    for n, p in (norm.image_types or {}).items()
                },
                "featureClass": {c: list(f) for c, f in (norm.features or {}).items() if f},
            }
            ext = featureextractor.RadiomicsFeatureExtractor(params)
            cache = {key: ext}  # keep one: a run uses one settings snapshot
            self._local.cache = cache
        return ext

    def extract(
        self, image_path: str, mask_path: str, label: int, settings: dict[str, Any]
    ) -> ExtractionResult:
        with _EXTRACT_LOCK:
            ext = self._extractor(settings)
            raw = ext.execute(image_path, mask_path, label=int(label))
        features: list[FeatureValue] = []
        diagnostics: dict[str, Any] = {}
        for key, value in raw.items():
            if key.startswith("diagnostics_"):
                diagnostics[key] = value
                continue
            image_type, feature_class, feature = key.split("_", 2)
            features.append(FeatureValue(image_type, feature_class, feature, _real(value)))
        return ExtractionResult(features=features, diagnostics=flatten_diagnostics(diagnostics))

    def dependency_versions(self) -> dict[str, str]:
        sitk: Any = importlib.import_module("SimpleITK")
        pywt: Any = importlib.import_module("pywt")
        return {
            "SimpleITK": str(sitk.Version_VersionString()),
            "numpy": str(np.__version__),
            "PyWavelets": str(pywt.__version__),
            "python": platform.python_version(),
        }


def rules(norm: RadiomicsSettings) -> list[Issue]:
    """RADIOMICS.md §Validation rules over normalized settings (selection rules: service)."""
    s = norm.settings or {}
    types = norm.image_types or {}
    feats = norm.features or {}
    out: list[Issue] = []
    if (s.get("binWidth") is None) == (s.get("binCount") is None):
        for k in ("binWidth", "binCount"):
            out.append(Issue(loc=["settings", k], msg=MSG_BINS, rule="bin_xor"))
    if "LoG" in types and not any(x > 0 for x in types["LoG"].get("sigma") or []):
        out.append(Issue(loc=["image_types", "LoG", "sigma"], msg=MSG_SIGMA, rule="log_sigma"))
    if not s.get("force2D"):
        if feats.get("shape2D"):
            out.append(Issue(loc=["features", "shape2D"], msg=MSG_2D, rule="force_2d"))
        if "LBP2D" in types:
            out.append(Issue(loc=["image_types", "LBP2D"], msg=MSG_2D, rule="force_2d"))
    rr = s.get("resegmentRange")
    mode = s.get("resegmentMode")
    if rr is not None:
        loc: list[str | int] = ["settings", "resegmentRange"]
        if mode == "sigma":
            if len(rr) != 1 or rr[0] <= 0:
                out.append(Issue(loc=loc, msg=MSG_RESEG_SIGMA, rule="reseg_sigma"))
        elif len(rr) == 2 and rr[0] >= rr[1]:
            out.append(Issue(loc=loc, msg=MSG_RESEG_ORDER, rule="reseg_order"))
        if s.get("normalize") and mode == "absolute":
            out.append(
                Issue(
                    loc=["settings", "normalize"],
                    msg=MSG_NORMALIZE_HU,
                    severity="warning",
                    rule="normalize_hu",
                )
            )
    if not any(feats.values()):
        out.append(Issue(loc=["features"], msg=MSG_NOTHING, rule="nothing"))
    if not types:
        out.append(Issue(loc=["image_types"], msg=MSG_NOTHING, rule="nothing"))
    return out
