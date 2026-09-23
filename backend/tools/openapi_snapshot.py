"""Write the reviewed OpenAPI contract snapshot (BE-10, TST-03).

cd backend && .venv/bin/python -m tools.openapi_snapshot   # after reviewing the diff
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SNAPSHOT = Path(__file__).resolve().parents[1] / "tests" / "openapi.snapshot.json"


def current() -> dict[str, Any]:
    from app.main import create_app

    spec: dict[str, Any] = create_app().openapi()
    return spec


def render(spec: dict[str, Any]) -> str:
    return json.dumps(spec, indent=1, sort_keys=True) + "\n"


def main() -> None:
    SNAPSHOT.write_text(render(current()), encoding="utf-8")
    print(f"wrote {SNAPSHOT}")


if __name__ == "__main__":
    main()
