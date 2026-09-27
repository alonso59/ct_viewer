"""Write the reviewed OpenAPI contract snapshot (BE-10, TST-03) and the frontend's copy (FE-03).

cd backend && .venv/bin/python -m tools.openapi_snapshot            # snapshot + frontend copy
cd backend && .venv/bin/python -m tools.openapi_snapshot --frontend PATH   # the copy only

`make gen-api` runs the first and regenerates `schema.d.ts`; `make api-types` (part of
`make check`) regenerates the types from the current spec into a scratch folder and diffs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SNAPSHOT = Path(__file__).resolve().parents[1] / "tests" / "openapi.snapshot.json"
# Input of `npm run gen:api` (git-ignored; its format is what `schema.d.ts` was generated from)
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "openapi.json"


def current() -> dict[str, Any]:
    from app.main import create_app

    spec: dict[str, Any] = create_app().openapi()
    return spec


def render(spec: dict[str, Any]) -> str:
    return json.dumps(spec, indent=1, sort_keys=True) + "\n"


def render_frontend(spec: dict[str, Any]) -> str:
    return json.dumps(spec, indent=1) + "\n"


def main(argv: list[str]) -> None:
    spec = current()
    if argv[:1] == ["--frontend"] and len(argv) == 2:
        Path(argv[1]).write_text(render_frontend(spec), encoding="utf-8")
        return
    if argv:
        raise SystemExit("usage: python -m tools.openapi_snapshot [--frontend PATH]")
    SNAPSHOT.write_text(render(spec), encoding="utf-8")
    FRONTEND.write_text(render_frontend(spec), encoding="utf-8")
    print(f"wrote {SNAPSHOT} and {FRONTEND}")


if __name__ == "__main__":
    main(sys.argv[1:])
