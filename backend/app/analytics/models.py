"""Request/response models for dashboard views (API-38, DB-*) and analyses (API-39, ANA-*).

Every item-bearing point, bar or cell carries `item_id` + `case_id` (DB-03) and the curation
status badge; colors are returned as category levels, the palette lives in the client (DB-07).
Floats that cannot be computed are `null`, never NaN.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Scope = Literal["complete", "voi"]
Side = Literal["L", "R", "-"]
Num = float | None

ViewSlug = Literal[
    "run-overview",
    "feature-distribution",
    "missing-matrix",
    "correlation",
    "embedding",
    "outliers",
    "feature-vs-volume",
    "group-comparison",
    "association",
    "balance",
    "phase-side-consistency",
]
TestName = Literal[
    "welch_t",
    "mann_whitney",
    "welch_anova",
    "kruskal_wallis",
    "spearman",
    "pearson",
    "chi2",
    "fisher",
]
EffectName = Literal[
    "cohens_d",
    "rank_biserial_r",
    "eta_squared",
    "epsilon_squared",
    "spearman_rho",
    "pearson_r",
    "cramers_v",
]
# ANA-04: `default` / `alternative` force the Tests-table column; `auto` applies the rule.
TestOverride = Literal["auto", "default", "alternative"]
Question = Literal["explore", "compare", "association", "balance", "paired"]
RecCode = Literal[
    "REC-SMALL-N",
    "REC-IMBALANCE",
    "REC-MISSING",
    "REC-CONFOUNDER",
    "REC-VOLUME",
    "REC-REDUNDANT",
    "REC-NONINDEP",
    "REC-NO-SIGNAL",
    "REC-MODALITY",
    "REC-COMPOSITIONAL",
]


# -- shared inputs --------------------------------------------------------------------------


class GlobalFilters(BaseModel):
    """DB-02 global filters, applied to every view and analysis (AND across fields).

    `var` uses the VAR-10 syntax: `{name: [values]}`, categorical values OR'ed, numeric
    `min..max` ranges. `status` is the curation status (CUR-08; unreviewed = `not_reviewed`).
    `item_ids` carries a DB-04 selection.
    """

    var: dict[str, list[str]] = Field(default_factory=dict)
    phase: list[str] | None = None
    scope: list[Scope] | None = None
    side: list[Side] | None = None
    label: list[int] | None = None
    status: list[str] | None = None
    item_ids: list[str] | None = None


class ColorBy(BaseModel):
    """DB-07 color/split: a categorical variable, an item attribute, or curation status."""

    kind: Literal["variable", "phase", "scope", "side", "label", "curation_status"]
    name: str | None = None  # the variable name when kind = variable

    @model_validator(mode="after")
    def _name_for_variable(self) -> ColorBy:
        if self.kind == "variable" and not self.name:
            raise ValueError("name is required when kind = 'variable'")
        return self


class UnitSpec(BaseModel):
    """ANA-03 unit of analysis: one label, one scope, one phase per case.

    `phase = null` picks, per case, the item whose phase ranks first in the project phase
    priority. `aggregate` resolves > 1 item per case: `first` (by phase priority, then
    scan, side), `mean` (feature means), or `none` (keep every item; triggers REC-NONINDEP).
    `label`/`scope` default to the most frequent in the filtered run.
    """

    label: int | None = None
    scope: Scope | None = None
    phase: str | None = None
    aggregate: Literal["first", "mean", "none"] = "first"


class ItemRef(BaseModel):
    """DB-03 hover/click target."""

    item_id: str
    case_id: str
    label: int
    status: str  # curation status badge (CUR-08)
    color: str | None = None  # DB-07 level of the color variable


class BoxStats(BaseModel):
    n: int
    min: Num = None
    q1: Num = None
    median: Num = None
    q3: Num = None
    max: Num = None
    whisker_low: Num = None
    whisker_high: Num = None
    mean: Num = None
    sd: Num = None


# -- view requests (API-38) -----------------------------------------------------------------


class ViewRequest(BaseModel):
    filters: GlobalFilters = Field(default_factory=GlobalFilters)


class RunOverviewRequest(ViewRequest):
    errors_limit: int = Field(default=200, ge=0, le=2000)


class FeatureDistributionRequest(ViewRequest):
    feature: str
    split: ColorBy | None = None
    log_scale: bool = False
    bins: int = Field(default=30, ge=2, le=200)


class MissingMatrixRequest(ViewRequest):
    feature_class: list[str] | None = None
    max_cells: int = Field(default=50_000, ge=1, le=50_000)


class CorrelationRequest(ViewRequest):
    feature_class: list[str] | None = None
    threshold: float = Field(default=0.9, gt=0, le=1)
    max_features: int = Field(default=200, ge=2, le=500)


class EmbeddingRequest(ViewRequest):
    features: list[str] | None = None
    feature_class: list[str] | None = None
    n_components: int = Field(default=2, ge=2, le=10)
    method: Literal["pca", "umap"] = "pca"
    color_by: ColorBy | None = None


class OutliersRequest(ViewRequest):
    threshold: float = Field(default=3.5, gt=0)
    top_n: int = Field(default=50, ge=1, le=5000)
    top_features: int = Field(default=5, ge=1, le=50)
    feature_class: list[str] | None = None


class FeatureVsVolumeRequest(ViewRequest):
    feature: str
    color_by: ColorBy | None = None
    top_n: int = Field(default=50, ge=1, le=2000)


class GroupComparisonRequest(ViewRequest):
    variable: str
    feature: str | None = None  # default: the top result row
    test: TestOverride = "auto"
    unit: UnitSpec = Field(default_factory=UnitSpec)
    features: list[str] | None = None
    feature_class: list[str] | None = None


class AssociationRequest(ViewRequest):
    variable: str
    feature: str | None = None
    test: TestOverride = "auto"  # alternative = Pearson
    unit: UnitSpec = Field(default_factory=UnitSpec)
    features: list[str] | None = None
    feature_class: list[str] | None = None


class BalanceRequest(ViewRequest):
    variable: str
    other: str
    test: TestOverride = "auto"  # alternative = Fisher
    unit: UnitSpec = Field(default_factory=UnitSpec)


class PairSpec(BaseModel):
    """`phase`: same case/scope/side/label across phases a vs b (default: first two phases
    by priority present). `side`: same scan/label, VOI sides a vs b (default L vs R)."""

    kind: Literal["phase", "side"] = "phase"
    a: str | None = None
    b: str | None = None


class ConsistencyRequest(ViewRequest):
    feature: str
    pair: PairSpec = Field(default_factory=PairSpec)


# -- view responses -------------------------------------------------------------------------


class LabelCount(BaseModel):
    label: int
    n_items: int
    n_values: int


class LevelCount(BaseModel):
    level: str
    n: int


class RunError(BaseModel):
    item_id: str | None = None
    case_id: str | None = None
    label: int | None = None
    message: str


class RunOverviewResponse(BaseModel):
    """Run overview: items ok/failed, per-label counts, runtime, error list → item."""

    run_id: str
    name: str
    status: str
    created_at: str | None = None
    runtime_s: Num = None
    n_items_selected: int
    n_items_ok: int
    n_items_failed: int
    n_features: int
    per_label: list[LabelCount]
    per_phase: list[LevelCount]
    curation: list[LevelCount]
    n_errors: int
    errors: list[RunError]


class DistPoint(ItemRef):
    value: float
    bin: int | None = None  # histogram bin of this item (bar → items, DB-03)


class DistGroup(BaseModel):
    level: str | None
    n: int
    n_missing: int  # NaN/inf, or ≤ 0 on a log scale
    counts: list[int]
    box: BoxStats


class FeatureDistributionResponse(BaseModel):
    feature: str
    split: ColorBy | None
    log_scale: bool
    edges: list[float]
    groups: list[DistGroup]
    points: list[DistPoint]
    truncated: bool = False


class MissingFeature(BaseModel):
    feature: str
    feature_class: str
    n_nan: int
    n_inf: int
    n_absent: int


class MissingItem(ItemRef):
    n_invalid: int


class MissingCell(BaseModel):
    item: int  # index into `items`
    feature: int  # index into `features`
    kind: Literal["nan", "inf", "absent"]


class MissingMatrixResponse(BaseModel):
    features: list[MissingFeature]
    items: list[MissingItem]  # only items with ≥ 1 invalid cell, worst first
    cells: list[MissingCell]
    n_items_total: int
    truncated: bool = False


class Cluster(BaseModel):
    features: list[str]


class CorrelationResponse(BaseModel):
    method: Literal["spearman"] = "spearman"
    features: list[str]  # clustered order (average linkage on 1 - |rho|)
    matrix: list[list[Num]]
    threshold: float
    clusters: list[Cluster]  # connected groups with |rho| > threshold (size ≥ 2)
    n_rows: int
    truncated: bool = False


class EmbeddingPoint(ItemRef):
    coords: list[float]


class Loading(BaseModel):
    feature: str
    weight: float


class EmbeddingResponse(BaseModel):
    method: Literal["pca", "umap"]
    n_components: int
    explained_variance_ratio: list[float]
    features_used: list[str]
    top_loadings: list[list[Loading]]
    color_levels: list[str]
    points: list[EmbeddingPoint]


class OutlierFeature(BaseModel):
    feature: str
    value: Num
    z: float


class OutlierItem(ItemRef):
    max_abs_z: float
    n_outlier_features: int
    top_features: list[OutlierFeature]


class OutlierFeatureCount(BaseModel):
    feature: str
    n_outlier_items: int


class OutliersResponse(BaseModel):
    threshold: float
    n_items: int
    n_flagged: int
    items: list[OutlierItem]
    features: list[OutlierFeatureCount]


class ScatterPoint(ItemRef):
    x: float
    y: float


class RankedFeature(BaseModel):
    feature: str
    rho: Num
    n: int


class FeatureVsVolumeResponse(BaseModel):
    feature: str
    volume_feature: str
    rho: Num
    p: Num
    n: int
    size_driven: bool  # |rho| > 0.8 (REC-VOLUME)
    color_levels: list[str]
    points: list[ScatterPoint]
    ranked: list[RankedFeature]  # features by |rho| with volume


class UnitPoint(BaseModel):
    """One unit row (ANA-03): representative item + the items it aggregates."""

    item_id: str
    case_id: str
    item_ids: list[str]
    status: str
    group: str | None = None
    x: Num = None
    value: Num = None


class GroupInfo(BaseModel):
    level: str
    n: int
    excluded: bool  # ANA-06: n < 5 → descriptive only


class TestChoice(BaseModel):
    """ANA-04: the rule outcome with a one-line reason."""

    default_test: TestName | None
    alternative_test: TestName | None
    override: TestOverride
    n_default: int
    n_alternative: int
    reason: str


class ResultRow(BaseModel):
    """ANA-05: one tested feature (or the single balance-check row)."""

    feature: str | None
    test: TestName | None
    reason: str
    statistic: Num = None
    p: Num = None
    q: Num = None
    effect: Num = None
    effect_name: EffectName | None = None
    n: int
    groups: list[str] = Field(default_factory=list)


class DescriptiveRow(BaseModel):
    """ANA-07 per feature x group."""

    feature: str
    group: str
    n: int
    missing: int
    median: Num = None
    q1: Num = None
    q3: Num = None
    iqr: Num = None
    mean: Num = None
    sd: Num = None
    excluded: bool = False


class UnitSummary(BaseModel):
    label: int
    scope: str
    phase: str | None
    aggregate: Literal["first", "mean", "none"]
    n_rows: int
    n_cases: int
    n_items: int
    max_items_per_case: int
    n_variable_missing: int = 0


class GroupComparisonResponse(BaseModel):
    variable: str
    feature: str | None
    unit: UnitSummary
    groups: list[GroupInfo]
    choice: TestChoice
    selected: ResultRow | None
    boxes: list[DistGroup]
    points: list[UnitPoint]
    results: list[ResultRow]
    descriptives: list[DescriptiveRow]  # of the selected feature


class AssociationResponse(BaseModel):
    variable: str
    feature: str | None
    unit: UnitSummary
    choice: TestChoice
    selected: ResultRow | None
    points: list[UnitPoint]
    results: list[ResultRow]


class ContingencyCell(BaseModel):
    row: str
    col: str
    n: int
    expected: Num = None
    item_ids: list[str]
    case_ids: list[str]


class Contingency(BaseModel):
    variable: str
    other: str
    rows: list[str]
    cols: list[str]
    cells: list[ContingencyCell]
    excluded_rows: list[str]
    excluded_cols: list[str]
    result: ResultRow


class BalanceResponse(BaseModel):
    unit: UnitSummary
    choice: TestChoice
    table: Contingency


class PairPoint(BaseModel):
    case_id: str
    item_id_a: str
    item_id_b: str
    label: int
    status_a: str
    status_b: str
    a: float
    b: float
    mean: float
    diff: float  # b - a


class ConsistencyResponse(BaseModel):
    feature: str
    kind: Literal["phase", "side"]
    a: str
    b: str
    n_pairs: int
    bias: Num
    sd_diff: Num
    loa_low: Num
    loa_high: Num
    rho: Num
    points: list[PairPoint]


# -- analyses (API-39) ----------------------------------------------------------------------


class AnalysisSpec(BaseModel):
    """ANA-01: run + filter + unit + question type + variable (+ optional confounder).

    `balance` compares `variable` x `confounder` (both categorical). `paired` (ANA-10) is
    planned for v3.1 and rejected with `validation`.
    """

    run_id: str
    name: str = Field(default="", max_length=200)
    question: Question
    variable: str | None = None
    confounder: str | None = None
    filters: GlobalFilters = Field(default_factory=GlobalFilters)
    unit: UnitSpec = Field(default_factory=UnitSpec)
    test: TestOverride = "auto"
    features: list[str] | None = None
    feature_class: list[str] | None = None


class Recommendation(BaseModel):
    """ANA-08: a triggered rule; `view` + `params` open the view that shows the problem."""

    code: RecCode
    message: str
    view: ViewSlug
    params: dict[str, str | float | int | bool | list[str] | None] = Field(default_factory=dict)


class AnalysisSummary(BaseModel):
    analysis_id: str
    name: str
    created_at: str
    created_by: str | None = None
    run_id: str
    question: Question
    variable: str | None
    confounder: str | None
    n_rows: int
    n_tested: int
    n_significant: int  # q < 0.05
    n_recommendations: int


class Analysis(BaseModel):
    """GET …/analyses/{aid}: results + descriptives + recommendations (DB-08)."""

    analysis_id: str
    created_at: str
    created_by: str | None = None
    spec: AnalysisSpec
    unit: UnitSummary
    groups: list[GroupInfo]
    choice: TestChoice
    results: list[ResultRow]
    descriptives: list[DescriptiveRow]
    recommendations: list[Recommendation]
    balance: Contingency | None = None


class AnalysisList(BaseModel):
    items: list[AnalysisSummary]
    next_cursor: str | None = None
    total: int
