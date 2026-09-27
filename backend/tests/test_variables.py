"""TST-01: variable profiling and catalog rules (VAR-01..09), derived variables (VAR-06),
external tables (VAR-07), `var.{name}` filters (VAR-10) and phase presets (PRJ-16)."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import ValidationProblem
from app.ingest.models import Item, PhaseInfo
from app.projects.presets import Pack, load_packs, normalize_phase_value
from app.variables.build import ExternalData, build, match_report
from app.variables.external import parse_table
from app.variables.models import (
    BinDef,
    DominantDef,
    ExternalTable,
    RecodeDef,
    VariableOverride,
)
from app.variables.profile import as_date, as_text, infer_type, parse_age_years
from app.variables.table import matching_ids, parse_var_params, to_arrow

# -- type inference (VARIABLES.md §Type inference rules) ---------------------------------------


def test_continuous_needs_numbers_and_ten_distinct() -> None:
    inf = infer_type([f"{v * 3.7:.1f}" for v in range(12)] + [None, None])
    assert (inf.type, inf.review) == ("continuous", False)


def test_numeric_with_few_distinct_is_discrete_and_needs_review() -> None:
    inf = infer_type(["0", "5", "7", "8", "10", "30", "5", None])
    assert (inf.type, inf.review) == ("numeric-discrete", True)


def test_mostly_numeric_with_stray_text_is_continuous_with_review() -> None:
    values = [f"{v}.5" for v in range(40)] + ["n/a"]
    inf = infer_type(values)
    assert inf.type == "continuous" and inf.review and 0.95 <= inf.confidence < 1


def test_categorical_by_distinct_count() -> None:
    assert infer_type(["NP", "CMP", "NC", "EP"] * 5).type == "categorical"
    vendors = ["SIEMENS", "Philips Medical Systems", "GE MEDICAL SYSTEMS"] * 10
    assert infer_type(vendors).type == "categorical"


def test_categorical_by_share_of_rows() -> None:
    values = [f"k{i % 30}" for i in range(1000)]  # 30 distinct > 20 but <= 5 % of rows
    assert infer_type(values).type == "categorical"


@pytest.mark.parametrize(
    "values",
    [
        ["2021-01-02", "2021-03-04", "2022-12-31"],
        ["20210102", "20210304", "20221231"],
        ["2021-01-02T10:00:00", "2021-01-03T11:30:00.123", "2021-01-04 09:00"],
    ],
)
def test_dates(values: list[str]) -> None:
    assert infer_type(values).type == "date"


def test_invalid_yyyymmdd_is_not_a_date() -> None:
    assert as_date("20211345") is None and as_date("20210229") is None
    assert as_date("20240229") == "2024-02-29"


def test_identifier_when_distinct_close_to_rows() -> None:
    assert infer_type([f"S{i:04d}-x" for i in range(50)]).type == "identifier"


def test_sequential_integers_are_an_identifier_with_review() -> None:
    inf = infer_type([str(i) for i in range(1, 60)])
    assert (inf.type, inf.review) == ("identifier", True)


def test_text_and_constant() -> None:
    text = [f"note {i % 25} about the series" for i in range(60)]
    assert infer_type(text).type == "text"
    assert infer_type(["converted"] * 9 + [None]).type == "constant"
    assert infer_type([None, None]).type == "constant"


def test_as_text_normalizes_json_scalars() -> None:
    assert as_text("") is None and as_text("  ") is None and as_text(None) is None
    assert as_text(5.0) == "5" and as_text(2.5) == "2.5" and as_text(True) == "true"
    assert as_text(float("nan")) is None and as_text({"a": 1}) is None


def test_dicom_age_strings() -> None:
    assert parse_age_years("045Y") == 45 and parse_age_years("006M") == 0.5
    assert parse_age_years("052W") == pytest.approx(0.9966, abs=1e-3)
    assert parse_age_years("40") == 40 and parse_age_years("old") is None


# -- catalog building --------------------------------------------------------------------------


def item(case: str, scan: str = "01", scope: str = "complete", **extra: Any) -> Item:
    pid = extra.pop("patient_id", f"P{case[-3:]}")
    return Item(
        item_id=f"{case}.{scan}.{scope}.{'L' if scope == 'voi' else '-'}",
        case_id=case,
        scan_idx=scan,
        scope=scope,  # type: ignore[arg-type]
        side="L" if scope == "voi" else "-",
        patient_id=pid,
        phase=PhaseInfo(canonical="NP"),
        import_id="I",
        extra=extra,
    )


def cohort(n: int = 30) -> list[Item]:
    """n cases x 2 scans with invented study and acquisition fields."""
    out: list[Item] = []
    for c in range(n):
        case = f"case_{c:05d}"
        study = {
            "alpha": str(10 + 3 * c) if c % 2 == 0 else "",
            "beta": str(90 - 3 * c) if c % 2 == 0 else "",
            "stage": str(c % 4),
        }
        for s in ("01", "02"):
            out.append(
                item(
                    case,
                    s,
                    **study,
                    manufacturer=("SIEMENS", "Siemens Healthineers", "PHILIPS")[c % 3],
                    kvp=str(100 + 20 * ((c + int(s)) % 3)),
                    tube=str(100 + 7 * c + int(s)),
                    series_uid=f"1.2.3.{c}.{s}",
                    first_file=f"/dicom/{case}/{s}/IM1",
                    accession_number=f"A{c}{s}",
                    scan_date=f"2021-01-{1 + c % 28:02d}",
                    status="converted",
                    raw_metadata={"PatientSex": "MF"[c % 2], "PatientAge": f"{30 + c:03d}Y"},
                )
            )
    return out


def by_name(items: list[Item], **kw: Any) -> dict[str, Any]:
    built, _ = build(items, **kw)
    return {v.name: v for v in built.catalog.variables}


def test_catalog_levels_groups_and_visibility() -> None:
    built, _ = build(cohort())
    cat = built.catalog
    v = {x.name: x for x in cat.variables}
    assert (v["alpha"].type, v["alpha"].level, v["alpha"].group) == ("continuous", "case", "study")
    assert v["alpha"].visible and v["alpha"].profile.missing_pct == 50.0
    assert v["alpha"].profile.n_units == 30  # case-level: one unit per case
    assert (v["stage"].type, v["stage"].review) == ("numeric-discrete", True)
    assert v["tube"].level == "scan" and v["tube"].profile.n_units == 60
    assert v["manufacturer"].group == "acquisition" and not v["manufacturer"].visible
    assert "confounder" in v["manufacturer"].tags and "confounder" in v["kvp"].tags
    assert v["status"].type == "constant" and not v["status"].visible
    assert v["scan_date"].type == "date" and "sensitive" in v["scan_date"].tags
    assert "sensitive" in v["patient_id"].tags and not v["patient_id"].visible
    reasons = {e.name: e.reason for e in cat.excluded}
    assert reasons == {
        "series_uid": "uid",
        "first_file": "path",
        "accession_number": "accession",
        "raw_metadata": "blob",
    }
    assert cat.n_cases == 30 and cat.n_items == 60


def test_raw_metadata_allowlist() -> None:
    v = by_name(cohort())
    assert v["patient_sex"].type == "categorical" and v["patient_sex"].source == "raw"
    assert v["patient_age"].type == "continuous" and v["patient_age"].profile.min == 30
    assert not any(n.startswith("Patient") for n in v)


def test_excluded_upstream_and_voi_rows_are_not_profiled() -> None:
    items = cohort(12)
    items.append(item("case_00099", status_x="x"))
    items[-1] = items[-1].model_copy(update={"status": "excluded_upstream"})
    items.append(item("case_00000", "01", scope="voi", voi_metric="1.0"))
    v = by_name(items)
    assert "status_x" not in v and "voi_metric" not in v


def test_override_confirms_type_and_clears_review() -> None:
    v = by_name(
        cohort(), overrides={"stage": VariableOverride(type="categorical", tags=["outcome"])}
    )
    st = v["stage"]
    assert (st.type, st.inferred_type, st.review, st.overridden) == (
        "categorical",
        "numeric-discrete",
        False,
        True,
    )
    assert st.tags == ["outcome"]


def test_table_joins_case_level_values_onto_every_item() -> None:
    items = [*cohort(10), item("case_00000", "01", scope="voi")]
    built, _ = build(items)
    t = to_arrow(built).to_pydict()
    rows = [i for i, iid in enumerate(t["item_id"]) if iid.startswith("case_00000.")]
    assert len(rows) == 3 and {t["alpha"][i] for i in rows} == {10.0}
    assert {t["kvp"][i] for i in rows} >= {120.0}  # scan-level joins by scan
    assert "series_uid" not in t and "raw_metadata" not in t


# -- derived (VAR-06) --------------------------------------------------------------------------


def test_bin_by_thresholds_with_labels() -> None:
    d = BinDef(name="alpha_bin", source="alpha", thresholds=[50], labels=["low", "high"])
    built, _ = build(cohort(), derived=[d])
    col = next(c for c in built.columns if c.var.name == "alpha_bin")
    assert col.var.level == "case" and col.var.type == "categorical"
    assert col.by_case["case_00000"] == "low"  # 10 < 50
    assert col.by_case["case_00014"] == "high"  # 52 >= 50
    assert col.by_case["case_00001"] is None  # source missing


def test_bin_by_quantiles_default_labels() -> None:
    d = BinDef(name="tube_q", source="tube", quantiles=[0.5])
    v = by_name(cohort(), derived=[d])
    assert len(v["tube_q"].profile.top) == 2
    assert all(t.value.startswith(("<", ">=")) for t in v["tube_q"].profile.top)


def test_recode_merges_vendor_strings() -> None:
    d = RecodeDef(
        name="vendor",
        source="manufacturer",
        map={"SIEMENS": "Siemens", "Siemens Healthineers": "Siemens", "PHILIPS": "Philips"},
    )
    v = by_name(cohort(), derived=[d])
    assert {t.value for t in v["vendor"].profile.top} == {"Siemens", "Philips"}


def test_dominant_names_the_largest_source() -> None:
    d = DominantDef(name="dom", sources=["alpha", "beta"])
    built, _ = build(cohort(), derived=[d])
    col = next(c for c in built.columns if c.var.name == "dom")
    assert col.by_case["case_00000"] == "beta" and col.by_case["case_00028"] == "alpha"
    assert col.by_case["case_00001"] is None


def test_dominant_tie() -> None:
    items = [item(f"case_{c:05d}", a=str(c % 3), b=str(c % 3), c3="0") for c in range(12)]
    built, _ = build(items, derived=[DominantDef(name="d", sources=["a", "b"])])
    col = next(c for c in built.columns if c.var.name == "d")
    assert set(col.by_case.values()) == {"tie"}


@pytest.mark.parametrize(
    "bad",
    [
        BinDef(name="x", source="nope", thresholds=[1]),
        BinDef(name="x", source="manufacturer", thresholds=[1]),
        BinDef(name="x", source="alpha", thresholds=[5, 1]),
        BinDef(name="x", source="alpha", thresholds=[5], quantiles=[0.5]),
        BinDef(name="x", source="alpha", thresholds=[5], labels=["one"]),
        RecodeDef(name="x", source="tube", map={}),
        DominantDef(name="x", sources=["alpha", "manufacturer"]),
        DominantDef(name="x", sources=["alpha", "alpha"]),
        BinDef(name="alpha", source="tube", thresholds=[1]),
        BinDef(name="phase", source="tube", thresholds=[1]),
    ],
)
def test_invalid_derived_definitions(bad: Any) -> None:
    with pytest.raises(ValidationProblem):
        build(cohort(), derived=[bad], strict={bad.name})
    built, info = build(cohort(), derived=[bad])
    assert info["derived_errors"]
    assert [b.name for b in built.catalog.broken] == [bad.name]  # AUD-A5-08: listed, deletable


# -- external tables (VAR-07) ------------------------------------------------------------------


def test_external_table_by_case_id() -> None:
    data = b"case_id,biopsy,volume_ml\ncase_00000,pos,12.5\ncase_00001,neg,3\ncase_77777,pos,1\n"
    key, cols, rows, dups, n = parse_table(data, "extra.csv")
    assert (key, cols, n, dups) == ("case_id", ["biopsy", "volume_ml"], 3, [])
    t = ExternalTable(
        table_id="T", filename="T.csv", key=key, columns=cols, sha256="0", imported_at="now"
    )
    ext = ExternalData(t, rows)
    items = cohort(4)
    assert match_report(ext, items) == (2, ["case_77777"])
    v = by_name(items, external=[ext])
    assert v["biopsy"].source == "external" and v["biopsy"].level == "case"
    assert v["biopsy"].profile.n_missing == 2  # cases 2 and 3 are not in the table


def test_external_table_tsv_by_patient_id_with_duplicates() -> None:
    data = b"patient_id\tsite\nP000\tA\nP001\tB\nP000\tC\n"
    key, cols, rows, dups, n = parse_table(data, "x.tsv")
    assert (key, cols, dups, n) == ("patient_id", ["site"], ["P000"], 3)
    assert rows["P000"] == {"site": "A"}


@pytest.mark.parametrize(
    "data",
    [b"", b"foo,bar\n1,2\n", b"case_id,a,a\nx,1,2\n", b"\xff\xfe"],
)
def test_external_table_errors(data: bytes) -> None:
    with pytest.raises(ValidationProblem):
        parse_table(data, "x.csv")


# -- filters (VAR-10) --------------------------------------------------------------------------


def test_parse_and_match_var_filters() -> None:
    built, _ = build(cohort(10))
    table = to_arrow(built)
    f = parse_var_params([("var.alpha", "..20"), ("phase", "NP"), ("var.manufacturer", "PHILIPS")])
    assert f == {"alpha": ["..20"], "manufacturer": ["PHILIPS"]}
    got = matching_ids(built.catalog, table, {"alpha": ["..20"]})
    assert got["cases"] == {"case_00000", "case_00002"}
    got = matching_ids(built.catalog, table, {"manufacturer": ["SIEMENS", "PHILIPS"]})
    assert "case_00001" not in got["cases"] and "case_00000" in got["cases"]
    got = matching_ids(built.catalog, table, {"kvp": ["120"], "alpha": ["0.."]})
    assert got["items"] and all(i.endswith("complete.-") for i in got["items"])
    with pytest.raises(ValidationProblem):
        matching_ids(built.catalog, table, {"missing_var": ["1"]})
    with pytest.raises(ValidationProblem):
        matching_ids(built.catalog, table, {"alpha": ["x..y"]})


# -- presets (PRJ-16) --------------------------------------------------------------------------


def test_preset_phase_normalization() -> None:
    packs = load_packs()
    cc, gen = packs["ccrcc"], packs["generic-ct"]
    none = Pack("none", "none", (), (), {}, ("UNK",))  # no pack: open vocabulary

    def norm(p: Any, raw: str | None) -> str:
        return normalize_phase_value(raw, list(p.phase_vocabulary), p.phase_mapping)

    assert [norm(cc, r) for r in ("art", "VEN", "delay", "nc", "", "weird")] == [
        "CMP",
        "NP",
        "EP",
        "NC",
        "UNK",
        "UNK",
    ]
    assert [norm(gen, r) for r in ("ART", "cmp", "venous", "NP", "Delayed", None)] == [
        "ART",
        "ART",
        "PV",
        "PV",
        "DELAYED",
        "UNK",
    ]
    assert [norm(none, r) for r in ("Arterial 35s", " ven ", "UNDEFINED")] == [
        "Arterial 35s",
        "ven",
        "UNK",
    ]
    assert set(cc.phase_mapping.values()) <= set(cc.phase_vocabulary)
    assert set(gen.phase_mapping.values()) <= set(gen.phase_vocabulary)
    assert [s.name for s in cc.label_map] == ["kidney", "tumor", "cyst"]
    assert gen.label_map == () and none.label_map == ()
