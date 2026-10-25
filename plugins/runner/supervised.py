"""Capability-checked local/server execution; project writes remain API-owned."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from plugins.protocol import utc_now, write_json_atomic
from plugins.runner import gpu, service
from plugins.runner.deployment import managed_output, overlaps, validate_config


def isolated_argv(python: Path | str, script: Path, *args: str) -> list[str]:
    """`-I`: the script's folder is not on sys.path, so plugin modules such as nnunet's
    `profile.py` cannot shadow the standard library (torch imports cProfile)."""
    return [str(python), "-I", str(script), *args]


def stopping(job: Path) -> bool:
    return (job / "cancel").exists() or (job / "pause").exists()


def acknowledge_control(job: Path, attempt: str) -> None:
    """Answer the API's latest pause/cancel request after verified cleanup of `attempt`."""
    try:
        request = json.loads((job / "control.json").read_text())
    except (OSError, ValueError):
        return
    if isinstance(request, dict) and isinstance(request.get("id"), str):
        write_json_atomic(job / "control-ack.json", {"id": request["id"], "attempt": attempt, "at": utc_now()})


def within(path: Path, roots: list[str]) -> bool:
    return any(path.is_relative_to(Path(root).resolve()) for root in roots)


class Supervisor:
    def __init__(self, path: Path, workspace: Path | None = None) -> None:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor) as handle:
            details = os.fstat(handle.fileno())
            if details.st_uid != os.getuid() or details.st_mode & 0o077 or not stat.S_ISREG(details.st_mode):
                raise ValueError("deployment configuration must be a private operator-owned regular file")
            self.config = validate_config(json.load(handle))
        if self.config["backend"] == "slurm":
            raise ValueError("SLURM execution is deferred until cluster acceptance")
        configured_workspace = Path(self.config["workspace"]).resolve()
        if workspace is not None and configured_workspace != workspace:
            raise ValueError("deployment workspace does not match the runner")
        self.workspace = configured_workspace
        self.python = Path(self.config["environment"]) / "bin/python"
        if not os.access(self.python, os.X_OK):
            raise ValueError("configured environment interpreter is unavailable")
        self.pool = gpu.Pool(
            Path(self.config.get("state_dir", str(Path.home() / ".local/state/radiology-workbench/gpu-pool")))
        )
        self.record: dict[str, Any] | None = None
        self.last_error = ""

    def diagnostics(self, *, verify_host: bool = False) -> dict[str, Any]:
        report = self.verify() if verify_host else {"ready": False, "blockers": ["effective_checks_not_run"]}
        return {
            **report,
            "backend": self.config["backend"],
            "limits": self.config["limits"],
            "gpu_inventory": [
                {key: value for key, value in row.items() if key != "pids"} | {"busy": not gpu.idle(row)}
                for row in gpu.inventory()
            ],
            "limitations": [
                "cooperative GPU access",
                "no aggregate storage quota",
                "logout may interrupt work",
                "trusted code and Unix identity",
            ],
        }

    def inventory_snapshot(self) -> dict[str, Any]:
        try:
            pool = self.config.get("gpu_pool", [])
            rows = [row for row in gpu.inventory() if row["uuid"] in pool or str(row["index"]) in pool]
            return {
                "at": utc_now(),
                "error": None,
                "devices": [
                    {key: value for key, value in row.items() if key != "pids"} | {"busy": not gpu.idle(row)}
                    for row in rows
                ],
            }
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return {"at": utc_now(), "devices": [], "error": "GPU inventory unavailable"}

    def verify(self) -> dict[str, Any]:
        from plugins.runner.probe import run_probe

        self.verify_allocation_policy()
        report = run_probe(unprivileged=True)
        if not report["ready"]:
            raise ValueError("unprivileged containment failed: " + ", ".join(report.get("blockers", [])))
        self.recover()
        return report

    def verify_allocation_policy(self) -> None:
        path = self.workspace / gpu.RESOURCE_POLICY
        if not path.exists():
            return
        policy = json.loads(path.read_text())
        if policy.get("policy") != 1 or policy.get("pool") != self.pool.identity():
            raise ValueError("DICOM/runner allocation differs; configure one shared HOST_ALLOCATION_ROOT/state_dir")

    def environment(self) -> dict[str, str]:
        return {
            "PATH": f"{self.python.parent}:/usr/local/bin:/usr/bin:/bin",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "NUMEXPR_MAX_THREADS": "1",
            "BLOSC_NTHREADS": "1",
            "nnUNet_def_n_proc": "1",
            "TORCHINDUCTOR_COMPILE_THREADS": "1",
            "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS": "1",
            "BLIS_NUM_THREADS": "1",
            "NUMBA_NUM_THREADS": "1",
            "MALLOC_CONF": "background_thread:false,narenas:2",
            "RW_CPU_WORKERS": str(self.config["limits"]["cpus"]),
            "nnUNet_results": self.config["model_roots"][0],
            **({"RW_NNUNET_PROFILES_DIR": self.config["profiles_dir"]} if "profiles_dir" in self.config else {}),
        }

    def recover(self) -> None:
        record = self.pool.read()
        if record is None:
            return
        if record.get("owner") == "dicom":
            self.last_error = "waiting for the participating DICOM allocation"
            return
        if record.get("workspace") != str(self.workspace):
            return  # another participating workspace owns the conservative host slot
        self._validate_record(record)
        self.record = record
        self.poll()

    def _validate_record(self, record: dict[str, Any]) -> None:
        if type(record.get("attempt_version")) is not int or record["attempt_version"] != 1:
            raise ValueError("unsupported attempt version; manual reconciliation required")
        service.unit_name(record["attempt"])
        job = Path(record["job"])
        if record.get("uid") != os.getuid() or job.is_symlink() or job.resolve().parent != self.workspace / "queue":
            raise ValueError("ambiguous attempt ownership; manual reconciliation required")

    def prepare(
        self,
        job: Path,
        manifest: dict[str, Any],
        plugin: Path,
        spec: dict[str, Any],
        selected: list[str],
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        output = Path(spec["output_dir"]).resolve()
        if not within(output, self.config["derived_roots"]):
            raise ValueError("output is outside approved derived roots")
        sources = [Path(item["image"]["path"]).resolve() for item in spec.get("items", []) if item.get("image")]
        if any(not within(path, self.config["source_roots"]) or not path.is_file() for path in sources):
            raise ValueError("input is outside approved source roots or missing")
        if any(overlaps(output, path) or overlaps(job, path) for path in sources):
            raise ValueError("input/output overlap")
        managed = [Path(value) for value in self.config.get("managed_datasets", [])]
        for dataset in managed:
            if (
                dataset.resolve() != dataset
                or (dataset / "derived").resolve() != dataset / "derived"
                or not (dataset / ".workbench/projects").is_dir()
            ):
                raise ValueError("managed dataset/output roots must be canonical registered paths")
            if any(path.is_relative_to(dataset / name) for path in sources for name in ("derived", ".workbench")):
                raise ValueError("managed generated/state data cannot be used as source input")
        for value in self.config["model_roots"]:
            root = Path(value).resolve()
            if overlaps(output, root) or overlaps(job, root):
                raise ValueError("resolved model roots overlap writable paths")
        for value in self.config["source_roots"]:
            root = Path(value).resolve()
            if overlaps(job, root) or (overlaps(output, root) and not managed_output(output, root, managed)):
                raise ValueError("resolved source/model roots overlap writable paths")
        output.mkdir(parents=True, exist_ok=True)
        command = [
            str(value).replace("{python}", str(self.python)).replace("{job_dir}", str(job))
            for value in manifest["runtime"]["command"]
        ]
        devices = [
            path
            for path in [
                Path("/dev/null"),
                Path("/dev/zero"),
                Path("/dev/random"),
                Path("/dev/urandom"),
                Path("/dev/nvidiactl"),
                Path("/dev/nvidia-uvm"),
                Path("/dev/nvidia-uvm-tools"),
                *[Path(f"/dev/nvidia{row['index']}") for row in rows if row["uuid"] in selected],
            ]
            if path.exists()
        ]
        writes = [str(job), str(output)]
        if Path("/dev/shm").is_dir():
            writes.append("/dev/shm")
        attempt = uuid.uuid4().hex
        return {
            "attempt_version": 1,
            "attempt": attempt,
            "runtime_alias": f"/tmp/rw-{attempt}",
            "uid": os.getuid(),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "workspace": str(self.workspace),
            "job": str(job),
            "gpus": selected,
            "invocation": "",
            "state": "launching",
            "at": utc_now(),
            "command": command,
            "native_commands": ["nnUNetv2_predict", "nnUNetv2_apply_postprocessing"]
            if manifest.get("id") == "segment.nnunet"
            else [],
            "cwd": str(plugin),
            "write_roots": writes,
            "devices": [str(path) for path in devices],
            "environment": {**self.environment(), "CUDA_VISIBLE_DEVICES": ",".join(selected)},
            "limits": self.config["limits"],
        }

    def start(self, job: Path, manifest: dict[str, Any], plugin: Path, claim: Any) -> bool:
        if self.record is not None or stopping(job):
            return False
        self.verify_allocation_policy()
        spec = json.loads((job / "job.json").read_text())
        if manifest.get("id") == "segment.nnunet":
            if self.config["limits"]["cpus"] < 3:
                raise ValueError("nnU-Net admission requires at least 3 CPU workers")
            result = subprocess.run(
                isolated_argv(self.python, plugin / "verify.py", str(job)),
                cwd=plugin,
                env=self.environment(),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                raise ValueError("nnU-Net admission refused: " + result.stderr.strip()[-1500:])
        pending = [
            item
            for item in spec.get("items", [])
            if item.get("item_id") not in (spec.get("resume") or {}).get("skip", [])
        ]
        settings = spec.get("settings") or {}
        cap = settings.get("gpu_cap", 1)
        requested = settings.get("gpu_ids") or []
        if (
            type(cap) is not int
            or not 1 <= cap <= self.config["limits"]["gpus"]
            or not isinstance(requested, list)
            or any(not isinstance(value, str) for value in requested)
        ):
            raise ValueError("invalid GPU request")
        count = min(max(1, len(pending)), cap, len(requested) if requested else cap)
        rows = gpu.inventory()
        try:
            selected = gpu.select_devices(rows, self.config.get("gpu_pool", []), requested, count)
        except ValueError as exc:
            self.last_error = str(exc)
            return False
        record = self.prepare(job, manifest, plugin, spec, selected, rows)
        if not self.pool.reserve(record, claim=lambda: claim(job)):
            self.last_error = "waiting for the participating host allocation"
            return False
        self.record = record
        write_json_atomic(job / "attempt.json", record)
        if stopping(job):
            self.pool.release(record["attempt"])
            self.record = None
            write_json_atomic(
                job / "exit.json",
                {"attempt": record["attempt"], "code": -15, "at": utc_now(), "cleanup_verified": True},
            )
            acknowledge_control(job, record["attempt"])
            return True
        try:
            (job / ".runtime").mkdir(mode=0o700, exist_ok=True)
            Path(record["runtime_alias"]).symlink_to(job / ".runtime", target_is_directory=True)
            service.launch(record, self.config["limits"], self.python, job)
            state = service.show(record["attempt"])
            if not service.owned(record, state):
                raise ValueError("attempt invocation identity was not verified")
            record.update(invocation=state["InvocationID"], state="running")
            self.pool.update(record)
            write_json_atomic(job / "attempt.json", record)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            self.last_error = str(exc)
            self.poll()
        return True

    def poll(self) -> None:
        record = self.record
        if record is None:
            return
        self._validate_record(record)
        state = service.show(record["attempt"])
        job = Path(record["job"])
        if record["state"] == "launching" and service.owned(record, state):
            record.update(invocation=state["InvocationID"], state="running")
            self.pool.update(record)
            write_json_atomic(job / "attempt.json", record)
        if state.get("SubState") == "exited" and service.owned(record, state):
            if not service.stop(record):
                self.last_error = "cleanup_pending: completed attempt did not stop"
                return
            state = service.show(record["attempt"])
        if not service.empty(state):
            if not service.owned(record, state):
                self.last_error = "cleanup_pending: attempt identity is ambiguous"
                return
            if (job / "cancel").exists():
                service.stop(record)
            return
        if record["state"] == "launching" and state.get("LoadState") == "not-found":
            self.last_error = "cleanup_pending: launch acknowledgement was lost"
            return
        try:
            rows = gpu.inventory()
            gpu.select_devices(rows, record["gpus"], record["gpus"], len(record["gpus"]))
        except (OSError, ValueError) as exc:
            self.last_error = f"cleanup_pending: GPU release unknown: {exc}"
            return
        try:
            outcome = json.loads((job / "worker-exit.json").read_text())
            code = outcome["code"] if outcome["attempt"] == record["attempt"] else 1
        except (OSError, ValueError, KeyError):
            code = 1
        alias = Path(record["runtime_alias"])
        if alias.is_symlink() and alias.readlink() == job / ".runtime":
            alias.unlink()
        elif alias.exists() or alias.is_symlink():
            self.last_error = "cleanup_pending: runtime alias ownership is ambiguous"
            return
        write_json_atomic(
            job / "exit.json",
            {"code": code, "at": utc_now(), "attempt": record["attempt"], "cleanup_verified": True},
        )
        record["state"] = "finished"
        write_json_atomic(job / "attempt.json", record)
        if not self.pool.release(record["attempt"]):
            raise ValueError("allocation generation changed during cleanup")
        acknowledge_control(job, record["attempt"])
        self.record = None
        self.last_error = ""

    def stop(self) -> None:
        if self.record is not None:
            if not service.stop(self.record):
                raise ValueError("cleanup_pending: attempt stop could not be verified")
            deadline = time.monotonic() + 10
            while self.record is not None and time.monotonic() < deadline:
                self.poll()
                if self.record is not None:
                    time.sleep(0.2)
