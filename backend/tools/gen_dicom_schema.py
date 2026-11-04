"""Copy `dicom.convert`'s id, version and settings schema from `plugins/dicom/task.json` into the
`rw_dicom` package, which ships without the plugin manifest (`make gen-dicom-schema`)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "plugins" / "dicom" / "task.json"
TARGET = ROOT / "plugins" / "dicom" / "src" / "rw_dicom" / "task_settings.json"


def expected() -> str:
    manifest = json.loads(MANIFEST.read_text())
    keep = {k: manifest[k] for k in ("id", "version", "settings_schema")}
    return json.dumps(keep, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if argv == ["--check"]:
        if TARGET.read_text() != expected():
            print("rw_dicom/task_settings.json differs from task.json: run make gen-dicom-schema")
            return 1
        return 0
    TARGET.write_text(expected())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
