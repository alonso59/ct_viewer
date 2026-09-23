"""Variable catalog records (VARIABLES.md §Storage; API-16..18)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

VarType = Literal[
    "continuous", "categorical", "numeric-discrete", "date", "identifier", "text", "constant"
]
# Types a user may pick when confirming or overriding an inference (VAR-03).
SettableType = Literal["continuous", "categorical", "date", "identifier", "text"]
Level = Literal["case", "scan"]
VarGroup = Literal["study", "acquisition"]
VarSource = Literal["metadata", "derived", "external", "raw"]
Tag = Literal["confounder", "outcome", "sensitive"]
ExcludeReason = Literal["core", "uid", "path", "blob", "accession", "reserved"]
NUMERIC_TYPES: frozenset[str] = frozenset({"continuous", "numeric-discrete"})


class ValueCount(BaseModel):
    value: str
    n: int


class Profile(BaseModel):
    """VAR-01: computed over units of the variable's level (cases or scans)."""

    n_units: int
    n_missing: int
    missing_pct: float
    distinct: int
    top: list[ValueCount] = Field(default_factory=list)  # most common values (≤ 20)
    examples: list[str] = Field(default_factory=list)  # ≤ 5
    numeric_pct: float = 0.0  # share of non-missing values that parse as numbers
    min: float | None = None
    max: float | None = None
    median: float | None = None


class Variable(BaseModel):
    name: str
    source: VarSource
    type: VarType
    inferred_type: VarType
    level: Level
    group: VarGroup
    tags: list[Tag] = Field(default_factory=list)
    visible: bool
    confidence: float  # 0..1
    review: bool  # VAR-03 "Review" badge: low confidence or numeric-discrete, until confirmed
    overridden: bool = False
    profile: Profile


class Excluded(BaseModel):
    """VAR-08/09: fields that are never variables, with the reason."""

    name: str
    reason: ExcludeReason


class BinDef(BaseModel):
    """VAR-06 bin: continuous → categorical by thresholds or quantiles (`v < t` → lower bin)."""

    op: Literal["bin"] = "bin"
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    source: str
    thresholds: list[float] | None = None
    quantiles: list[float] | None = None  # each in (0, 1)
    labels: list[str] | None = None  # len = number of bins


class RecodeDef(BaseModel):
    """VAR-06 recode: merge/rename categories; unmapped values are kept as they are."""

    op: Literal["recode"] = "recode"
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    source: str
    map: dict[str, str]


class DominantDef(BaseModel):
    """VAR-06 dominant: name of the largest of N numeric variables (missing if any is missing;
    `tie` when several share the maximum)."""

    op: Literal["dominant"] = "dominant"
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    sources: list[str] = Field(min_length=2)


DerivedDef = Annotated[BinDef | RecodeDef | DominantDef, Field(discriminator="op")]


class ExternalTable(BaseModel):
    """VAR-07 external case-keyed table, snapshotted under `variables/external/`."""

    table_id: str
    filename: str
    key: Literal["case_id", "patient_id"]
    columns: list[str]
    sha256: str
    imported_at: str


class ExternalReport(BaseModel):
    table: ExternalTable
    n_rows: int
    n_matched: int
    n_unmatched: int
    unmatched_keys: list[str]  # first 50
    duplicate_keys: list[str]  # first 50; the first row wins
    conflicts: list[str]  # columns skipped because the name is already taken


class VariableOverride(BaseModel):
    """API-16 PATCH body; only provided fields change (VAR-03/05)."""

    type: SettableType | None = None
    visible: bool | None = None
    tags: list[Tag] | None = None


class Catalog(BaseModel):
    """`variables/catalog.json` (VAR-11) and the API-16 response."""

    schema_version: Literal[1] = 1
    profiled_at: str | None = None
    import_id: str | None = None
    n_items: int = 0
    n_cases: int = 0
    variables: list[Variable] = Field(default_factory=list)
    excluded: list[Excluded] = Field(default_factory=list)
    derived: list[DerivedDef] = Field(default_factory=list)
    external: list[ExternalTable] = Field(default_factory=list)
    overrides: dict[str, VariableOverride] = Field(default_factory=dict)

    def get(self, name: str) -> Variable | None:
        return next((v for v in self.variables if v.name == name), None)
