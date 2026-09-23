"""TST-02: input parsers, phase normalization table, side parser (IMP-02/03, INPUT_METADATA.md)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.ingest.normalize import (
    PHASE_TABLE,
    normalize_phase,
    parse_side,
    resolve_phase,
    seg_convention,
)
from app.ingest.parsers import (
    Row,
    is_excluded,
    parse_inputs,
    parse_metadata,
    parse_phase_json,
    parse_voi_catalog,
)


def jsonl(*rows: Any) -> bytes:
    return "".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows).encode()


SCAN = {"case_id": "case_00001", "scan_idx": "01", "filename": "01_case_00001_0000.nii.gz"}


def test_metadata_valid_row_and_extra() -> None:
    rows, errors = parse_metadata(jsonl({**SCAN, "phase": "VEN", "scanner": "X1"}))
    assert errors == []
    assert rows[0].line == 1 and rows[0].text("phase") == "VEN"
    assert rows[0].extra == {"scanner": "X1"}  # unknown fields preserved


def test_metadata_line_numbered_errors() -> None:
    data = jsonl(
        SCAN,
        "{not json",
        "[1, 2]",
        {"scan_idx": "01", "filename": "a.nii.gz"},
        {"case_id": "case_1", "scan_idx": "01", "filename": "a.nii.gz"},
        {"case_id": "case_00002", "scan_idx": "0 1", "filename": "a.nii.gz"},
        {"case_id": "case_00002", "scan_idx": "01"},
        '{"case_id": "case_00003", "scan_idx": "01", "filename": "a", "x": NaN}',
    )
    data = data.replace(b"\n", b"\n\n", 1)  # blank lines are skipped but still counted
    rows, errors = parse_metadata(data)
    assert [r.case_id for r in rows] == ["case_00001"]
    got = [(e.line, e.field) for e in errors]
    assert got == [
        (3, None),
        (4, None),
        (5, "case_id"),
        (6, "case_id"),
        (7, "scan_idx"),
        (8, "filename"),
        (9, None),
    ]


def test_metadata_numeric_scan_idx_and_excluded_without_filename() -> None:
    rows, errors = parse_metadata(
        jsonl(
            {"case_id": "case_00001", "scan_idx": 2, "nifti_file": "/d/x.nii"},
            {"case_id": "case_00022", "scan_idx": "01", "status": "skipped"},
        )
    )
    assert errors == []
    assert rows[0].scan_idx == "2" and is_excluded(rows[1])


@pytest.mark.parametrize(
    ("fields", "excluded"),
    [
        ({"status": "skipped"}, True),
        ({"status": "SKIPPED"}, True),
        ({"planned_conversion": "false"}, True),
        ({"planned_conversion": False}, True),
        ({"curated_keep": "0"}, True),
        ({"curated_keep": "no"}, True),
        ({"status": "converted", "planned_conversion": "true", "curated_keep": True}, False),
        ({}, False),
    ],
)
def test_is_excluded(fields: dict[str, Any], excluded: bool) -> None:
    assert is_excluded(Row(1, fields)) is excluded


def test_phase_json_both_forms_and_errors() -> None:
    ov, errors = parse_phase_json(
        json.dumps(
            {
                "schema_version": 1,
                "phases": [
                    {"case_id": "case_00001", "scan_idx": "01", "phase": "NP"},
                    {"case_id": "bad", "scan_idx": "01", "phase": "NP"},
                    "x",
                ],
                "phase_by_filename": {"01_case_00002_0000.nii.gz": "ART", "y": 3},
            }
        ).encode()
    )
    assert ov.lookup("case_00001", "01", None) == "NP"
    assert ov.lookup("case_00002", "01", "01_case_00002_0000.nii.gz") == "ART"
    assert len(ov) == 2
    assert [e.field for e in errors] == ["phases[1]", "phases[2]", "phase_by_filename[y]"]


@pytest.mark.parametrize("data", [b"", b"{", b"[]", b'{"x": 1}', b"\xff\xfe"])
def test_phase_json_invalid_top_level(data: bytes) -> None:
    ov, errors = parse_phase_json(data)
    assert len(ov) == 0 and len(errors) == 1


def test_voi_catalog_required_fields() -> None:
    rows, errors = parse_voi_catalog(
        jsonl(
            {"case_id": "case_00001", "scan_idx": "01", "side": "L", "image_path": "v.nii.gz",
             "dice": 0.9},
            {"case_id": "case_00001", "scan_idx": "01", "image_path": "v.nii.gz"},
            {"case_id": "case_00001", "scan_idx": "01", "side": "R"},
        )
    )  # fmt: skip
    assert len(rows) == 1 and rows[0].extra == {"dice": 0.9}
    assert [(e.line, e.field) for e in errors] == [(2, "side"), (3, "image_path")]


def test_parse_inputs_metadata_only() -> None:
    parsed = parse_inputs({"metadata": jsonl(SCAN)})  # IMP-11
    assert len(parsed.metadata) == 1 and parsed.catalog == [] and len(parsed.overrides) == 0


# --- phase resolution --------------------------------------------------------------------

TABLE = {
    "NC": ["NC", "NONCONTRAST", "NON-CONTRAST"],
    "CMP": ["ART", "ARTERIAL", "CMP", "CORTICOMEDULLARY"],
    "NP": ["VEN", "VENOUS", "NP", "NEPHROGRAPHIC", "PORTAL"],
    "EP": ["EP", "DELAY", "DELAYED", "EXC", "EXCRETORY"],
    "UNK": ["", "UNDEFINED", "UNKNOWN", "N/A", "NONE"],
}


def test_phase_table_matches_doc() -> None:
    assert {raw: code for code, raws in TABLE.items() for raw in raws} == PHASE_TABLE


@given(
    st.sampled_from([(raw, code) for code, raws in TABLE.items() for raw in raws]),
    st.lists(st.booleans(), max_size=20),
    st.sampled_from(["", " ", "\t"]),
)
def test_phase_normalization_case_insensitive(
    pair: tuple[str, str], flips: list[bool], pad: str
) -> None:
    raw, code = pair
    mixed = "".join(c.lower() if i < len(flips) and flips[i] else c for i, c in enumerate(raw))
    assert normalize_phase(pad + mixed + pad) == code


@given(st.text(max_size=20))
def test_phase_unknown_strings_are_unk(text: str) -> None:
    code = normalize_phase(text)
    assert code in ("NC", "CMP", "NP", "EP", "UNK")
    if text.strip().upper() not in PHASE_TABLE:
        assert code == "UNK"


def test_resolve_phase_order_and_ambiguity() -> None:
    row = Row(1, {"phase": "VEN", "canonical_phase": "NP", "phase_guess": "ART"})
    info, amb = resolve_phase(row, None)
    assert (info.canonical, info.raw, info.source, amb) == ("NP", "NP", "canonical_phase", False)
    info, amb = resolve_phase(row, "EP")
    assert (info.canonical, info.source, amb) == ("EP", "phase.json", False)
    conflict = Row(1, {"curated_phase": "ART", "phase": "VEN"})
    assert resolve_phase(conflict, None)[1] is True
    assert resolve_phase(conflict, "NP")[1] is False  # override wins silently
    guess_only = Row(1, {"phase": "UNDEFINED", "phase_guess": "NP"})
    info, amb = resolve_phase(guess_only, None)
    assert (info.canonical, info.source, amb) == ("UNK", "phase", True)
    info, amb = resolve_phase(Row(1, {"phase_guess": "art"}), None)
    assert (info.canonical, info.source, amb) == ("CMP", "phase_guess", False)
    info, amb = resolve_phase(Row(1, {}), None)
    assert (info.canonical, info.source, amb) == ("UNK", "none", True)


# --- side / seg convention ---------------------------------------------------------------

SIDES = {"L": ["L", "left", "sideL", "_L"], "R": ["R", "right", "sideR", "_R"]}


@given(
    st.sampled_from([(v, s) for s, vs in SIDES.items() for v in vs]),
    st.booleans(),
    st.sampled_from(["", " "]),
)
def test_parse_side_accepts(pair: tuple[str, str], upper: bool, pad: str) -> None:
    value, side = pair
    assert parse_side(pad + (value.upper() if upper else value.lower()) + pad) == side


@given(st.text(max_size=12))
def test_parse_side_rejects_others(text: str) -> None:
    valid = {v.lower() for vs in SIDES.values() for v in vs}
    assert (parse_side(text) is None) == (text.strip().lower() not in valid)


@pytest.mark.parametrize(
    ("name", "seg"),
    [
        ("01_case_00001_0000.nii.gz", "seg/01_case_00001.nii.gz"),
        ("01_case_00001_0000.nii", "seg/01_case_00001.nii"),
        ("x_0000_0000.NII.GZ", "seg/x_0000.NII.GZ"),
        ("plain.nii.gz", "seg/plain.nii.gz"),
    ],
)
def test_seg_convention(name: str, seg: str) -> None:
    assert seg_convention(name) == seg


# --- robustness --------------------------------------------------------------------------

junk_line = st.one_of(
    st.binary(max_size=60),
    st.text(max_size=60).map(str.encode),
    st.recursive(
        st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(),
        lambda c: st.lists(c, max_size=4) | st.dictionaries(st.text(max_size=8), c, max_size=4),
        max_leaves=10,
    ).map(lambda v: json.dumps(v).encode()),
    st.fixed_dictionaries(
        {"case_id": st.text(max_size=12), "scan_idx": st.text(max_size=4) | st.integers()},
        optional={
            "filename": st.text(max_size=8),
            "side": st.text(max_size=4),
            "image_path": st.text(max_size=8),
            "status": st.text(max_size=8),
        },
    ).map(lambda v: json.dumps(v).encode()),
)


@given(st.lists(junk_line, max_size=12))
def test_parsers_never_crash(lines: list[bytes]) -> None:
    data = b"\n".join(lines)
    n_lines = sum(1 for ln in data.split(b"\n") if ln.strip())
    for parse in (parse_metadata, parse_voi_catalog):
        rows, errors = parse(data)
        assert all(e.line is not None and e.line >= 1 for e in errors)
        assert len(rows) <= n_lines
        assert all(r.case_id.startswith("case_") for r in rows)
    ov, errors = parse_phase_json(data)
    assert isinstance(len(ov), int)
