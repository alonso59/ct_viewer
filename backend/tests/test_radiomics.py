"""Radiomics engine layer: schema (RAD-01/02), validation rules (RAD-04), profile hash (RAD-03),
IBSI map + digital phantom compliance (TST-06). API-level behaviour: test_radiomics_api.py."""

from __future__ import annotations

import inspect
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.radiomics import ibsi
from app.radiomics import settings as st
from app.radiomics.models import RadiomicsSettings

pytest.importorskip("radiomics")

from app.radiomics.engine import get_engine
from app.radiomics.pyradiomics_engine import CODE_DEFAULTS, PyRadiomicsEngine

DATA = Path(__file__).parent / "data" / "radiomics"


@pytest.fixture(scope="module")
def eng() -> PyRadiomicsEngine:
    e = get_engine()
    assert isinstance(e, PyRadiomicsEngine)
    return e


# -- schema (RAD-01/02) -------------------------------------------------------------------


def test_schema_options_groups_defaults(eng: PyRadiomicsEngine) -> None:
    s = eng.schema()
    opts = {o.name: o for o in s.options}
    groups = {g.id for g in s.groups}
    assert all(o.group in groups for o in s.options)
    assert "label" not in opts  # selection-driven (RAD-05)
    expect = {
        "binWidth": ("discretization", 25.0),
        "binCount": ("discretization", None),
        "resampledPixelSpacing": ("resampling", None),
        "interpolator": ("resampling", "sitkBSpline"),
        "padDistance": ("resampling", 5),
        "preCrop": ("resampling", False),
        "normalize": ("intensity", False),
        "normalizeScale": ("intensity", 1.0),
        "removeOutliers": ("intensity", None),
        "voxelArrayShift": ("intensity", 0),
        "resegmentRange": ("resegmentation", None),
        "resegmentMode": ("resegmentation", "absolute"),
        "resegmentShape": ("resegmentation", False),
        "minimumROIDimensions": ("mask", 2),
        "minimumROISize": ("mask", None),
        "geometryTolerance": ("mask", None),
        "correctMask": ("mask", False),
        "force2D": ("two_d", False),
        "force2Ddimension": ("two_d", 0),
        "distances": ("texture", [1]),
        "symmetricalGLCM": ("texture", True),
        "weightingNorm": ("texture", None),
        "gldm_a": ("texture", 0),
        "additionalInfo": ("output", True),
    }
    for name, (group, default) in expect.items():
        assert opts[name].group == group, name
        assert opts[name].default == default, name
    assert opts["resegmentMode"].constraints.enum == ["absolute", "relative", "sigma"]
    assert opts["binWidth"].constraints.min == 0 and opts["binWidth"].constraints.exclusive_min
    assert opts["resampledPixelSpacing"].constraints.min_items == 3
    assert "other" not in {o.group for o in s.options}  # every engine option is mapped


def test_schema_filters_and_features(eng: PyRadiomicsEngine) -> None:
    s = eng.schema()
    filters = {f.name: f for f in s.filters}
    assert set(filters) >= {
        "Original", "LoG", "Wavelet", "Square", "SquareRoot", "Logarithm", "Exponential",
        "Gradient", "LBP2D", "LBP3D",
    }  # fmt: skip
    assert [n for n, f in filters.items() if f.default_enabled] == ["Original"]
    wav = {p.name: p for p in filters["Wavelet"].params}
    assert wav["wavelet"].default == "coif1" and wav["level"].default == 1
    assert "coif1" in (wav["wavelet"].constraints.enum or [])
    assert [p.name for p in filters["LoG"].params] == ["sigma"]
    assert filters["LBP2D"].requires_2d
    classes = {c.name: c for c in s.feature_classes}
    assert set(classes) == {
        "firstorder", "shape", "shape2D", "glcm", "glrlm", "glszm", "gldm", "ngtdm",
    }  # fmt: skip
    assert not classes["shape2D"].default_enabled and classes["shape2D"].requires_2d
    for c in classes.values():
        for f in c.features:
            assert f.default_enabled == (not f.deprecated)
            assert f.ibsi.status in ("compliant", "deviates", "not_defined")
    glcm = {f.name: f for f in classes["glcm"].features}
    assert glcm["SumVariance"].deprecated and not glcm["SumVariance"].default_enabled
    assert glcm["Contrast"].ibsi.code == "ACUI"
    d = s.defaults
    assert d.image_types == {"Original": {}}
    assert d.features is not None and "shape2D" not in d.features
    assert d.features["firstorder"] and "StandardDeviation" not in d.features["firstorder"]
    assert sum(len(v or []) for v in d.features.values()) == 107
    assert s.ibsi_map_version == "1" and s.engine.name == "pyradiomics"


def test_code_defaults_match_engine_source() -> None:
    """`CODE_DEFAULTS` mirrors the inline `kwargs.get(name, default)` defaults of the engine."""
    import radiomics

    src = "\n".join(
        inspect.getsource(importlib_module)
        for importlib_module in (
            radiomics.imageoperations, radiomics.glcm, radiomics.gldm, radiomics.firstorder,
            radiomics.featureextractor,
        )
    )  # fmt: skip
    pat = re.compile(r'(?:kwargs|_?settings)\.get\(\s*"(\w+)"\s*,\s*([^)\n]+?)\s*\)')
    found: dict[str, list[str]] = {}
    for name, raw in pat.findall(src):
        found.setdefault(name, []).append(raw)
    for name, default in CODE_DEFAULTS.items():
        if name not in found:
            assert default is None, f"{name}: no inline default in the engine"
            continue
        values = []
        for raw in found[name]:
            try:
                values.append(eval(raw, {"sitk": None}))  # literals only
            except Exception:
                continue
        norm = [float(v) if isinstance(v, int) and not isinstance(v, bool) else v for v in values]
        want = (
            float(default)
            if isinstance(default, int) and not isinstance(default, bool)
            else default
        )
        assert want in norm or default in values, (name, default, found[name])


# -- validation rules (RAD-04, RADIOMICS.md §Validation rules) -----------------------------


def rules_of(eng: PyRadiomicsEngine, settings: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(i.rule, i.severity, i.msg) for i in eng.validate(settings)]


@pytest.mark.parametrize(
    ("settings", "rule", "msg", "loc"),
    [
        (
            {"settings": {"binCount": 16}},
            "bin_xor",
            "Choose bin width or bin count",
            ["settings", "binWidth"],
        ),
        (
            {"settings": {"binWidth": None}},
            "bin_xor",
            "Choose bin width or bin count",
            ["settings", "binCount"],
        ),
        (
            {"image_types": {"Original": {}, "LoG": {}}},
            "log_sigma",
            "LoG needs at least one sigma",
            ["image_types", "LoG", "sigma"],
        ),
        (
            {"image_types": {"LoG": {"sigma": [0]}}},
            "constraint",
            "LoG needs at least one sigma",
            ["image_types", "LoG", "sigma", 0],
        ),
        (
            {"features": {"shape2D": None}},
            "force_2d",
            "Enable 2D mode for this option",
            ["features", "shape2D"],
        ),
        (
            {"image_types": {"LBP2D": {}}},
            "force_2d",
            "Enable 2D mode for this option",
            ["image_types", "LBP2D"],
        ),
        (
            {"settings": {"resampledPixelSpacing": [1, -1, 1]}},
            "constraint",
            "Spacing must be positive",
            ["settings", "resampledPixelSpacing", 1],
        ),
        (
            {"settings": {"resampledPixelSpacing": [1, 1]}},
            "constraint",
            "Spacing must be positive",
            ["settings", "resampledPixelSpacing"],
        ),
        (
            {"settings": {"resegmentRange": [100, -100]}},
            "reseg_order",
            "Minimum must be less than maximum",
            ["settings", "resegmentRange"],
        ),
        (
            {"settings": {"resegmentRange": [-1, 2], "resegmentMode": "sigma"}},
            "reseg_sigma",
            "Sigma mode needs one positive value",
            ["settings", "resegmentRange"],
        ),
        ({"features": {}}, "nothing", "Nothing to extract", ["features"]),
        ({"image_types": {}}, "nothing", "Nothing to extract", ["image_types"]),
        ({"settings": {"nope": 1}}, "unknown", "Unknown option", ["settings", "nope"]),
        ({"settings": {"binWidth": "wide"}}, "type", "Must be a number", ["settings", "binWidth"]),
        ({"settings": {"force2D": 1}}, "type", "Must be true or false", ["settings", "force2D"]),
        (
            {"settings": {"interpolator": "sitkCubic"}},
            "constraint",
            None,
            ["settings", "interpolator"],
        ),
        ({"image_types": {"Bogus": {}}}, "unknown", "Unknown filter", ["image_types", "Bogus"]),
        ({"features": {"glcm": ["Nope"]}}, "unknown", "Unknown feature", ["features", "glcm", 0]),
        ({"image_types": {"LBP3D": {}}}, "unavailable", None, ["image_types", "LBP3D"]),
    ],
)
def test_validation_rules(
    eng: PyRadiomicsEngine, settings: dict[str, Any], rule: str, msg: str | None, loc: list[Any]
) -> None:
    if (
        rule == "unavailable"
        and next(f for f in eng.schema().filters if f.name == "LBP3D").available
    ):
        pytest.skip("LBP3D dependencies installed")
    issues = [i for i in eng.validate(settings) if i.rule == rule]
    assert issues, rules_of(eng, settings)
    assert any(i.loc == loc for i in issues), [i.loc for i in issues]
    assert all(i.severity == "error" for i in issues)
    if msg is not None:
        assert any(i.msg == msg for i in issues)


def test_validation_valid_and_warning(eng: PyRadiomicsEngine) -> None:
    assert eng.validate({}) == []
    ok = {
        "image_types": {"Original": {}, "LoG": {"sigma": [2, 1]}, "LBP2D": {}},
        "features": {"shape2D": None, "firstorder": ["Mean"]},
        "settings": {"force2D": True, "binWidth": None, "binCount": 32},
    }
    assert [i for i in eng.validate(ok) if i.severity == "error"] == []
    issues = eng.validate({"settings": {"normalize": True, "resegmentRange": [-100, 300]}})
    assert [(i.rule, i.severity, i.msg) for i in issues] == [
        ("normalize_hu", "warning", "HU range will be applied after normalization")
    ]
    assert eng.validate({"settings": {"resegmentRange": [2], "resegmentMode": "sigma"}}) == []


# -- canonical JSON / profile hash (RAD-03) -----------------------------------------------


def test_profile_hash_canonicalization(eng: PyRadiomicsEngine) -> None:
    schema = eng.schema()

    def h(raw: dict[str, Any]) -> str:
        norm, issues = st.normalize(schema, RadiomicsSettings.model_validate(raw))
        assert norm is not None, issues
        return st.profile_hash(norm, eng.name, st.engine_major(eng.version))

    base = h({})
    assert base.startswith("sha256:") and len(base) == 7 + 64
    assert h({"settings": {"binWidth": 25}}) == base  # int vs float
    assert h({"settings": {"binWidth": 25.0, "padDistance": 5}}) == base  # explicit defaults
    assert (
        h(
            {
                "features": {
                    c: None
                    for c in ("firstorder", "shape", "glcm", "glrlm", "glszm", "gldm", "ngtdm")
                }
            }
        )
        == base
    )
    assert h({"image_types": {"LoG": {"sigma": [2.0, 1]}}}) == h(
        {"image_types": {"LoG": {"sigma": [1, 2]}}}
    )  # set-like list
    assert h({"features": {"glcm": ["Contrast", "Id"]}}) == h(
        {"features": {"glcm": ["Id", "Contrast"]}}
    )
    assert h({"settings": {"binWidth": 10}}) != base
    norm, _ = st.normalize(schema, RadiomicsSettings())
    assert norm is not None
    assert st.profile_hash(norm, "pyradiomics", "4") != base  # engine major is part of it
    assert st.canonical_json({"b": 1.0, "a": [0.5, -0.0]}) == '{"a":[0.5,0],"b":1}'
    assert st.engine_major("3.1.1.dev111+g8ed579383") == "3"


# -- IBSI map + digital phantom (TST-06) --------------------------------------------------


def test_ibsi_map_covers_engine(eng: PyRadiomicsEngine) -> None:
    m = ibsi.ibsi_map()
    assert m["version"] == "1"
    classes = {c.name: {f.name for f in c.features} for c in eng.schema().feature_classes}
    assert {k: set(v) for k, v in m["features"].items()} == classes
    codes = [e["code"] for f in m["features"].values() for e in f.values() if e["code"]]
    assert all(re.fullmatch(r"[0-9A-Z]{4}", c) for c in codes)
    assert ibsi.export_info("wavelet-LLH", "glcm", "Contrast") == ("ACUI", "not_defined")
    assert ibsi.export_info("original", "glcm", "Contrast") == ("ACUI", "compliant")


def _phantom(tmp: Path) -> tuple[str, str]:
    import SimpleITK as sitk

    from tools.spikes.ibsi_phantom_smoke import IMAGE, MASK

    paths = []
    for name, arr in (("image", IMAGE), ("mask", MASK)):
        im = sitk.GetImageFromArray(np.asarray(arr, dtype=np.int16))
        im.SetSpacing((2.0, 2.0, 2.0))
        p = tmp / f"phantom_{name}.nrrd"
        sitk.WriteImage(im, str(p))
        paths.append(str(p))
    return paths[0], paths[1]


def test_ibsi_digital_phantom_compliance(eng: PyRadiomicsEngine, tmp_path: Path) -> None:
    """TST-06: `compliant` features match the IBSI reference; `deviates` via their conversion."""
    ref = json.loads((DATA / "ibsi_digital_phantom.json").read_text())
    rel = float(ref["tolerance"]["relative"])
    n = int(ref["roi_voxels"])
    all_features = {c.name: [f.name for f in c.features] for c in eng.schema().feature_classes}
    raw = RadiomicsSettings(
        features={c: all_features[c] for c in ref["reference"]}, settings={"binWidth": 1.0}
    )
    norm, issues = st.normalize(eng.schema(), raw)
    assert norm is not None, issues
    image, mask = _phantom(tmp_path)
    res = eng.extract(image, mask, 1, norm.model_dump(mode="json"))
    got = {
        (f.feature_class, f.feature): f.value for f in res.features if f.image_type == "original"
    }
    conversions = {
        ("firstorder", "Kurtosis"): lambda v: v - 3.0,  # non-excess → excess
        **{
            ("shape", a): (lambda v: v * math.sqrt(n / (n - 1)))
            for a in ("MajorAxisLength", "MinorAxisLength", "LeastAxisLength")
        },
    }
    results: dict[str, Any] = {}
    failures = []
    checked = {"compliant": 0, "deviates": 0}
    for cls, feats in ibsi.ibsi_map()["features"].items():
        for name, entry in feats.items():
            status = entry["status"]
            if status == "not_defined":
                continue
            assert name in ref["reference"].get(cls, {}), f"no IBSI reference for {cls}.{name}"
            want = float(ref["reference"][cls][name])
            value = got[(cls, name)]
            if status == "deviates":
                assert (cls, name) in conversions, f"deviation without conversion: {cls}.{name}"
                value = conversions[(cls, name)](value)
            ok = abs(value - want) <= rel * abs(want) + 1e-9
            results[f"{cls}.{name}"] = {"value": value, "ibsi": want, "status": status, "ok": ok}
            checked[status] += 1
            if not ok:
                failures.append((cls, name, value, want))
    assert not failures, failures
    assert checked == {"compliant": 85, "deviates": 4}
    out = tmp_path / "tst06.json"
    out.write_text(json.dumps({"ibsi_map_version": ibsi.map_version(), "results": results}))
    assert json.loads(out.read_text())["ibsi_map_version"] == "1"
    diag = res.diagnostics
    assert diag["Mask-original_VoxelNum"] == n
    assert "Versions_PyRadiomics" in diag
