"""DCM/BE-16: conservative per-series native working-set admission; no pixel calibration."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

MIB = 1024**2


class MemoryBudgetExceeded(Exception):
    def __init__(self, budget: int, required: int | None):
        self.detail = {
            "budget_mb": budget,
            "required_mb": required,
            "reason": "unknown_geometry" if required is None else "memory_budget",
            "remedy": "configure:DICOM_MEMORY_MB",
        }
        super().__init__(
            "Native conversion needs known geometry and a larger DICOM_MEMORY_MB budget"
            if required is None
            else f"Native conversion needs {required} MiB; DICOM_MEMORY_MB is {budget} MiB"
        )


def require_memory(row: dict[str, Any], header: Any, budget: int | None) -> None:
    if budget is None:  # standalone callers own their resource policy; the API requires one
        return
    try:
        dimensions = [int(row.get(k) or 0) for k in ("dim_x", "dim_y", "num_slices")]
        samples = int(getattr(header, "SamplesPerPixel", 1) or 1)
        if min([*dimensions, samples]) < 1:
            raise ValueError
        # Reader/rescale, reorientation and compression buffers; allow float64 intermediates.
        working = math.prod(dimensions) * max(8, math.ceil(int(getattr(header, "BitsAllocated", 16)) / 8)) * samples * 6
        vm = next(
            int(line.split()[1]) * 1024
            for line in Path("/proc/self/status").read_text().splitlines()
            if line.startswith("VmSize:")
        )
        native_imports = 384 * MIB if "SimpleITK" not in sys.modules else 0
        required = math.ceil((vm + native_imports + 128 * MIB + working) / MIB)
    except (ValueError, TypeError, OSError, StopIteration):
        raise MemoryBudgetExceeded(budget, None) from None
    if required > budget:
        raise MemoryBudgetExceeded(budget, required)
