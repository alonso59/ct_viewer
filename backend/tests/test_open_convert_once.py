"""Open mode DICOM: concurrent requests for one volume convert it once (root cause of the flaky
cold-run `tasks-dicom.spec.ts`: the viewer's image load and "Save as NIfTI…" raced on the same
scratch temp file, and the loser's rename failed)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.api.v1 import sources


class FakeJobs:
    def __init__(self) -> None:
        self.calls = 0

    async def run_in_worker(self, fn: Any, root: str, files: list[str], dst: str) -> str | None:
        self.calls += 1
        await asyncio.sleep(0.05)
        Path(dst).write_bytes(b"nii")
        return None


def test_concurrent_callers_share_one_conversion(tmp_path: Path) -> None:
    jobs = FakeJobs()
    ctx: Any = SimpleNamespace(jobs=jobs)
    dst = tmp_path / "volume.nii.gz"

    async def both() -> list[str | None]:
        calls = (sources._convert_once(ctx, "/r", ["a.dcm"], dst) for _ in range(3))
        return list(await asyncio.gather(*calls))

    assert asyncio.run(both()) == [None, None, None]
    assert jobs.calls == 1 and dst.read_bytes() == b"nii"
    assert sources._converting == {}  # nothing left in flight


def test_two_writers_of_one_volume_both_succeed(tmp_path: Path) -> None:
    """Across processes (no shared future), temp names are unique and the loser sees the file."""
    from concurrent.futures import ThreadPoolExecutor

    from app.tasks import dicom_stage
    from tools.dicom_fixtures import write_series

    write_series(tmp_path / "s")
    files = sorted(p.name for p in (tmp_path / "s").iterdir())
    dst = tmp_path / "out" / "volume.nii.gz"
    dst.parent.mkdir()
    with ThreadPoolExecutor(4) as pool:
        errs = list(
            pool.map(lambda _: dicom_stage.convert_series(str(tmp_path / "s"), files, str(dst)),
                     range(4))
        )  # fmt: skip
    assert errs == [None] * 4 and dst.is_file()
    assert [p.name for p in dst.parent.iterdir()] == ["volume.nii.gz"]  # no temp left behind
