"""TST-24/B05/B06: private HTTP API with the existing native ITK test barrier."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def held_index(batch: Any, *, root: Path) -> Any:
    import time

    from app.core.fsio import atomic_write_json
    from app.ingest.indexer import probe_batch

    result = probe_batch(batch)
    if (root / "hold-index").exists():
        atomic_write_json(root / "index-barrier.json", {"pid": os.getpid()})
        while (root / "hold-index").exists():
            time.sleep(0.01)
    return result


def staged_worker(job_dir: Path, stage: str) -> int:
    from threading import Event

    from plugins.analyzers import checkpoint
    from plugins.dicom import convert, scan

    from app.core.fsio import atomic_write_json
    from app.tasks import dicom_worker

    if stage == "fail-pixel":
        original_write = convert.write_nifti

        def fail(series: Any, *args: Any, **kwargs: Any) -> Any:
            if series.dicom_dir.name == "P1":
                raise OSError("Synthetic pixel publication failure")
            return original_write(series, *args, **kwargs)

        convert.write_nifti = fail
        return dicom_worker.main(job_dir)

    module = checkpoint if stage == "analyzing" else scan
    symbol = (
        "write_seed"
        if stage == "analyzing"
        else "image_info"
        if stage == "discovering"
        else "inspect"
    )
    original = getattr(module, symbol)

    def held(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        atomic_write_json(job_dir / "stage-barrier.json", {"pid": os.getpid(), "stage": stage})
        if stage == "analyzing":
            import time

            while not (job_dir / "release-stage").exists():
                time.sleep(0.01)
        else:
            Event().wait()
        return result

    setattr(module, symbol, held)
    return dicom_worker.main(job_dir)


def main() -> None:
    from functools import partial

    import uvicorn

    from app.config import Settings
    from app.ingest import indexer
    from app.main import create_app
    from app.tasks import dicom_process
    from tools.dicom_fixtures import write_series

    root, port, public_url = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    indexer.probe_batch = partial(held_index, root=root)
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
            stage = (root / "pause").read_text()
            if stage in {"discovering", "planning", "analyzing", "fail-pixel"}:
                staged = (
                    "import sys; from pathlib import Path; "
                    "from tests.dicom_browser_server import staged_worker; "
                    "raise SystemExit(staged_worker(Path(sys.argv[1]), sys.argv[2]))"
                )
                return await original(args[0], "-c", staged, args[3], stage, **kwargs)
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
