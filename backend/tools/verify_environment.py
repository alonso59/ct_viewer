"""Fail required test lanes before collection when their environment is incomplete."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from typing import Any

LEAN_MODULES = ("pytest", "xdist", "httpx", "hypothesis", "numpy", "nibabel", "SimpleITK")
FULL_MODULES = ("radiomics", "pywt", "yaml")


def check(*, full: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    packages: dict[str, str] = {}
    if sys.version_info[:2] != (3, 12):
        errors.append("The backend test lane requires Python 3.12")
    if full and hasattr(os, "geteuid") and os.geteuid() == 0:
        errors.append("Full tests require a non-root UID to verify source permission checks")
    required = () if errors else LEAN_MODULES + (FULL_MODULES if full else ())
    for name in required:
        try:
            module = importlib.import_module(name)
            packages[name] = str(getattr(module, "__version__", "installed"))
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    return {
        "ready": not errors,
        "errors": errors,
        "packages": packages,
        "python": ".".join(str(value) for value in sys.version_info[:3]),
        "full": full,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full", action="store_true", help="Require the radiomics/IBSI environment"
    )
    args = parser.parse_args()
    report = check(full=args.full)
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
