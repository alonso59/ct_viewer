"""TST-24/B05/B06: private HTTP API with the existing native ITK test barrier."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import uvicorn

from app.config import Settings
from app.main import create_app
from app.tasks import dicom_process
from tools.dicom_fixtures import write_series


def main() -> None:
    root, port, public_url = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    source = root / "source"
    if not source.exists():
        for index in range(2):
            write_series(
                source / f"P{index}",
                patient_id=f"P{index}",
                shape=(5, 4, 12),
                marker=(2, 1, 3),
                seed="browser-native-recovery",
            )
    (root / "derived").mkdir(exist_ok=True)
    original = dicom_process.asyncio.create_subprocess_exec
    code = (
        "import sys; from pathlib import Path; from threading import Event; "
        "from tests.test_dicom_operation_recovery import native_writer_child; "
        "native_writer_child(Path(sys.argv[1]), 0.0, Event().wait)"
    )

    async def launch(*args: Any, **kwargs: Any) -> Any:
        if args[1:3] == ("-m", "app.tasks.dicom_worker") and (root / "pause").exists():
            return await original(args[0], "-c", code, args[3], **kwargs)
        return await original(*args, **kwargs)

    dicom_process.asyncio.create_subprocess_exec = launch
    settings = Settings(
        workspace_root=root / "workspace",
        allowed_data_roots=str(source),
        allowed_derived_roots=str(root / "derived"),
        host_allocation_root=root / "allocation",
        public_base_url=public_url,
        job_workers=1,
        dicom_cpu_threads=1,
        dicom_memory_mb=1024,
        dicom_cleanup_seconds=0.2,
        _env_file=None,
    )  # type: ignore[call-arg]
    uvicorn.run(create_app(settings), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
