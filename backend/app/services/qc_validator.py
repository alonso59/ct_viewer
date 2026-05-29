from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.models.database import DatabaseValidationReport, QCWarning
from app.services.database import get_database_index, required_column_status


def validate_database(dataset_path: Path | str) -> DatabaseValidationReport:
    index = get_database_index(dataset_path)
    if not index.has_database:
        return DatabaseValidationReport(dataset_id=index.dataset_id, has_database=False)

    warnings = [warning for row in index.rows for warning in row.qc_warnings]
    duplicate_ids = _duplicate_row_id_warnings(index.rows)
    duplicate_combinations = _duplicate_scope_combination_warnings(index.rows)
    warnings.extend(duplicate_ids)
    warnings.extend(duplicate_combinations)

    return DatabaseValidationReport(
        dataset_id=index.dataset_id,
        has_database=True,
        row_count=len(index.rows),
        case_count=len({row.case_id for row in index.rows}),
        required_columns=required_column_status(index.fieldnames),
        missing_paths=[warning for warning in warnings if warning.code == "missing_path"],
        unreadable_files=[warning for warning in warnings if warning.code == "unreadable_file"],
        duplicate_row_identities=duplicate_ids,
        duplicate_scope_combinations=duplicate_combinations,
        missing_seg=[warning for warning in warnings if warning.code == "missing_seg"],
        missing_voi_image=[warning for warning in warnings if warning.code == "missing_voi_image"],
        missing_voi_mask=[warning for warning in warnings if warning.code == "missing_voi_mask"],
        ambiguous_phase=[warning for warning in warnings if warning.code == "ambiguous_phase"],
        ambiguous_side=[warning for warning in warnings if warning.code == "ambiguous_side"],
        warnings=warnings,
    )


def _duplicate_row_id_warnings(rows) -> list[QCWarning]:
    counts = Counter(row.row_id for row in rows)
    return [
        QCWarning(
            code="duplicate_row_identity",
            message=f"Row identity '{row_id}' appears {count} times.",
            severity="error",
            row_id=row_id,
        )
        for row_id, count in counts.items()
        if count > 1
    ]


def _duplicate_scope_combination_warnings(rows) -> list[QCWarning]:
    keys: Counter[tuple[str, str, str, str, str]] = Counter()
    for row in rows:
        if row.has_complete_scope:
            keys[(row.case_id, row.canonical_phase, row.scan_idx or "", row.side or "", "complete")] += 1
        if row.has_voi_scope:
            keys[(row.case_id, row.canonical_phase, row.scan_idx or "", row.side or "", "voi")] += 1

    return [
        QCWarning(
            code="duplicate_scope_combination",
            message=(
                f"{scope} combination for case={case_id}, phase={phase}, "
                f"scan_idx={scan_idx or '-'}, side={side or '-'} appears {count} times."
            ),
            severity="error",
            scope=scope,  # type: ignore[arg-type]
        )
        for (case_id, phase, scan_idx, side, scope), count in keys.items()
        if count > 1
    ]
