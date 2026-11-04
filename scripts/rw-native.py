#!/usr/bin/env python3
"""Native deployment: run the app from conda environments, without a container.

    python3 scripts/rw-native.py prepare                 # release + environment + smoke, no restart
    python3 scripts/rw-native.py deploy TAG              # switch production; restores it on failure
    python3 scripts/rw-native.py rollback                # back to the release before the last deploy

No sudo: conda environments and systemd user units only. Node builds the web app (`--node-env`, or
`npm` on PATH) and never runs in production. Standard library only, so any Python 3 can start it.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
UNITS = Path.home() / ".config/systemd/user"
APP_UNIT, RUNNER_UNIT = "radiology-workbench.service", "radiology-workbench-nnunet.service"
IDLE = {"completed", "failed", "cancelled", "completed_with_errors", "interrupted", "paused", "succeeded"}
EXPORTED = ["backend", "plugins", "frontend"]
SCRIPTS = ["container_app.py", "ctflow.py", "rw-runner.py"]


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def digest(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def conda() -> str:
    found = os.environ.get("CONDA_EXE") or shutil.which("conda") or str(Path.home() / "miniconda3/bin/conda")
    if not Path(found).exists():
        raise SystemExit("conda was not found; set CONDA_EXE")
    return found


def env_prefix(name: str) -> Path | None:
    listed = subprocess.run([conda(), "env", "list", "--json"], capture_output=True, text=True, check=True).stdout
    for prefix in json.loads(listed)["envs"]:
        if Path(prefix).name == name:
            return Path(prefix)
    return None


def python_env(name: str, tree: Path) -> Path:
    """The backend's pinned dependencies; reinstalled only when the lock changes."""
    prefix = env_prefix(name)
    if prefix is None:
        run(conda(), "create", "-y", "-q", "-n", name, "python=3.12", "pip")
        prefix = env_prefix(name)
        assert prefix is not None
    lock = tree / "backend/requirements-ci.lock"
    stamp = prefix / "rw-lock.sha256"
    if not stamp.exists() or stamp.read_text().strip() != digest(lock):
        # As the Dockerfile: dependencies of `backend[radiomics]`, then drop the empty distribution.
        package = tree / "deps"
        (package / "app").mkdir(parents=True)
        (package / "app/__init__.py").touch()
        shutil.copy2(tree / "backend/pyproject.toml", package / "pyproject.toml")
        pip = [str(prefix / "bin/python"), "-m", "pip"]
        run(*pip, "install", "-q", "-c", str(lock), f"{package}[radiomics]")
        run(*pip, "uninstall", "-q", "-y", "radiology-workbench")
        stamp.write_text(digest(lock) + "\n")
    return prefix


def build_web(frontend: Path, node_env: str | None) -> None:
    prefix: Path | None = None
    if shutil.which("npm") is None:
        prefix = env_prefix(node_env or "rwnode")
        if prefix is None:
            raise SystemExit("npm is not on PATH and the Node conda environment does not exist (--node-env)")
    env = {**os.environ}
    if prefix is not None:
        env["PATH"] = f"{prefix / 'bin'}:{env['PATH']}"
    run("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", cwd=frontend, env=env)
    run("npm", "run", "-s", "build", cwd=frontend, env=env)


def prepare(args: argparse.Namespace) -> int:
    state: Path = args.state
    commit = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    day = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d")
    tag = f"native-{day}-{commit[:7]}"
    release = state / "releases" / tag
    if release.exists():
        raise SystemExit(f"{release} exists")
    with tempfile.TemporaryDirectory(prefix="rw-native-", dir=state) as scratch:
        tree = Path(scratch) / "tree"
        tree.mkdir()
        archive = Path(scratch) / "src.tar"
        run(
            "git", "-C", str(REPO), "archive", "-o", str(archive), commit, *EXPORTED, *(f"scripts/{s}" for s in SCRIPTS)
        )
        with tarfile.open(archive) as source:
            source.extractall(tree, filter="data")
        build_web(tree / "frontend", args.node_env)
        prefix = python_env(args.python_env, tree)
        staged = Path(scratch) / "release"
        (staged / "backend").mkdir(parents=True)
        for name in ("app", "tools"):
            shutil.copytree(tree / "backend" / name, staged / "backend" / name)
        shutil.copytree(tree / "plugins", staged / "plugins")
        shutil.copytree(tree / "scripts", staged / "scripts")
        shutil.copytree(tree / "frontend/dist", staged / "static")
        meta = {
            "tag": tag,
            "commit": commit,
            "python_env": str(prefix),
            "lock_sha256": digest(tree / "backend/requirements-ci.lock"),
            "index_sha256": digest(staged / "static/index.html"),
        }
        (staged / "release.json").write_text(json.dumps(meta, indent=2) + "\n")
        staged.rename(release)
    env = {**os.environ, **release_env(release), "HOME": os.environ["HOME"]}
    python = str(prefix / "bin/python")
    try:
        run(python, "-m", "tools.spikes.ibsi_phantom_smoke", cwd=release / "backend", env=env)
        run(python, "-m", "tools.dicom_image_smoke", cwd=release / "backend", env=env)
    except subprocess.CalledProcessError:
        print(f"Smoke tests failed; {release} is kept for inspection and was not deployed", file=sys.stderr)
        return 1
    print(json.dumps(meta))
    return 0


def release_env(release: Path) -> dict[str, str]:
    return {
        "PYTHONPATH": f"{release / 'backend'}:{release / 'plugins/dicom/src'}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "ARROW_DEFAULT_MEMORY_POOL": "system",
    }


class Api:
    def __init__(self, port: str) -> None:
        self.base = f"http://127.0.0.1:{port}"

    def get(self, path: str) -> Any:
        with urllib.request.urlopen(self.base + "/api/v1" + path, timeout=30) as response:
            return json.load(response)

    def rows(self, path: str) -> list[dict[str, Any]]:
        data = self.get(path)
        return list(data if isinstance(data, list) else data.get("items", []))

    def blockers(self, pool: Path) -> list[str]:
        found = [j["job_id"] + ":" + j["status"] for j in self.rows("/jobs") if j["status"] not in IDLE]
        for project in self.rows("/projects"):
            runs = self.rows(f"/projects/{project['project_id']}/task-runs")
            found += [r["run_id"] + ":" + r["status"] for r in runs if r["status"] not in IDLE]
        if (pool / "lease.json").exists():
            found.append("GPU allocation held")
        return found


def poll(probe: Callable[[], Any], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if probe():
                return True
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
            pass
        time.sleep(2)
    return False


def systemctl(*args: str) -> None:
    run("systemctl", "--user", *args)


def app_unit(state: Path, release: Path, prefix: Path) -> str:
    return f"""[Unit]
Description=Radiology Workbench local production (native)
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory={release / "backend"}
EnvironmentFile={state / "config/runtime.env"}
EnvironmentFile={state / "config/native.env"}
Environment=PATH={prefix / "bin"}:/usr/local/bin:/usr/bin:/bin
ExecStart={prefix / "bin/python"} {release / "scripts/container_app.py"}
Restart=always
RestartSec=3
TimeoutStopSec=30
KillMode=control-group
UMask=0022

[Install]
WantedBy=default.target
"""


def runner_ready(state: Path) -> bool:
    for path in (state / "workspace/queue/runners").glob("*.json"):
        beat = json.loads(path.read_text())
        fresh = time.time() - path.stat().st_mtime < 30 and "segment.nnunet" in (beat.get("tasks") or [])
        if fresh and any(p.get("available") for p in (beat.get("model_catalog") or {}).get("profiles") or []):
            return True
    return False


def not_socket(folder: str, names: list[str]) -> set[str]:
    return {n for n in names if stat.S_ISSOCK(os.lstat(os.path.join(folder, n)).st_mode)}


def write_native_env(state: Path, release: Path, pool: Path) -> None:
    values = {
        **release_env(release),
        "CONTAINER_MODE": "0",
        "STATIC_ROOT": str(release / "static"),
        "HOST_ALLOCATION_ROOT": str(pool),
    }
    (state / "config/native.env").write_text("".join(f"{k}={v}\n" for k, v in values.items()))


def restore(backup: Path, state: Path, pool: Path) -> None:
    """The saved release, units and plugin link; the workspace copy stays a manual decision."""
    has_runner = (backup / RUNNER_UNIT).exists()
    subprocess.run(["systemctl", "--user", "stop", RUNNER_UNIT, APP_UNIT], check=False)
    previous = json.loads((backup / "release.json").read_text())
    if previous.get("deployment_kind") == "native-conda":
        # The unit reads release paths from this file, so a stale one would keep running the new code.
        write_native_env(state, state / "releases" / previous["tag"], pool)
    shutil.copy2(backup / "release.json", state / "config/release.json")
    shutil.copy2(backup / APP_UNIT, UNITS / APP_UNIT)
    if has_runner:
        shutil.copy2(backup / RUNNER_UNIT, UNITS / RUNNER_UNIT)
    link = backup / "plugin-link.txt"
    if link.exists():
        current = state / "plugins/nnunet"
        temporary = current.with_name("nnunet.next")
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(link.read_text().strip())
        temporary.replace(current)
    systemctl("daemon-reload")
    systemctl("start", APP_UNIT, *([RUNNER_UNIT] if has_runner else []))


def deploy(args: argparse.Namespace) -> int:
    state: Path = args.state
    release = (state / "releases" / args.tag).resolve()
    meta = json.loads((release / "release.json").read_text())
    prefix = Path(meta["python_env"])
    if digest(release / "static/index.html") != meta["index_sha256"]:
        raise SystemExit("The release changed since it was prepared")
    current = json.loads((state / "config/release.json").read_text())
    port = next(
        line.split("=", 1)[1]
        for line in (state / "config/runtime.env").read_text().splitlines()
        if line.startswith("PORT=")
    )
    api = Api(port)
    pool: Path = args.allocation
    waiting = api.blockers(pool)
    if waiting:
        raise SystemExit("Work is active; wait for it: " + ", ".join(waiting))
    projects = {p["project_id"] for p in api.rows("/projects")}
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = state / "releases" / f"pre-{meta['tag']}-{stamp}"
    backup.mkdir(mode=0o700)
    shutil.copy2(state / "config/release.json", backup / "release.json")
    shutil.copy2(state / "config/runtime.env", backup / "runtime.env")
    shutil.copy2(UNITS / APP_UNIT, backup / APP_UNIT)
    runner = UNITS / RUNNER_UNIT
    link = state / "plugins/nnunet"
    has_runner = runner.exists()
    if has_runner:
        shutil.copy2(runner, backup / RUNNER_UNIT)
    if link.is_symlink():
        (backup / "plugin-link.txt").write_text(os.readlink(link) + "\n")
    units = (RUNNER_UNIT, APP_UNIT) if has_runner else (APP_UNIT,)
    systemctl("stop", *units)
    try:
        if (pool / "lease.json").exists():
            raise RuntimeError("A GPU allocation appeared")
        shutil.copytree(state / "workspace", backup / "workspace", symlinks=True, ignore=not_socket)
        write_native_env(state, release, pool)
        (UNITS / APP_UNIT).write_text(app_unit(state, release, prefix))
        if has_runner:
            text = runner.read_text()
            start = next(line for line in text.splitlines() if line.startswith("ExecStart="))
            parts = start.split()
            parts[1] = str(release / "scripts/rw-runner.py")
            parts[parts.index("--plugins") + 1] = str(release / "plugins")
            runner.write_text(text.replace(start, " ".join(parts)))
            temporary = link.with_name("nnunet.next")
            temporary.unlink(missing_ok=True)
            temporary.symlink_to(release / "plugins/nnunet", target_is_directory=True)
            temporary.replace(link)
        record = {
            **{k: v for k, v in current.items() if k not in {"image", "image_tar_sha256", "container"}},
            **meta,
            "deployment_kind": "native-conda",
            "deployed_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "rollback": str(backup),
        }
        (state / "config/release.json").write_text(json.dumps(record, indent=2) + "\n")
        systemctl("daemon-reload")
        systemctl("start", *units)
        if not poll(lambda: api.get("/health")["status"] == "ok", 120):
            raise RuntimeError("The app did not become healthy")
        if {p["project_id"] for p in api.rows("/projects")} != projects:
            raise RuntimeError("The project list changed")
        with urllib.request.urlopen(api.base + "/", timeout=30) as response:
            if hashlib.sha256(response.read()).hexdigest() != meta["index_sha256"]:
                raise RuntimeError("The served web app differs from the release")
        if has_runner:
            if not poll(lambda: runner_ready(state), 240):
                raise RuntimeError("The runner did not advertise a validated profile")
            if not poll(lambda: api.get("/tasks/segment.nnunet")["available"], 120):
                raise RuntimeError("segment.nnunet is not available")
    except Exception as exc:  # noqa: BLE001 - any failure restores the previous release
        print(f"Deploy failed, restoring the previous release: {exc}", file=sys.stderr)
        restore(backup, state, pool)
        print("healthy again:", poll(lambda: api.get("/health")["status"] == "ok", 180), file=sys.stderr)
        return 1
    print(json.dumps({"deployed": meta["tag"], "commit": meta["commit"], "backup": str(backup)}))
    return 0


def rollback(args: argparse.Namespace) -> int:
    state: Path = args.state
    backup = Path(json.loads((state / "config/release.json").read_text())["rollback"])
    restore(backup, state, args.allocation)
    print(json.dumps({"restored": str(backup)}))
    return 0


def main() -> int:
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", type=Path, default=home / ".local/share/radiology-workbench")
    parser.add_argument("--allocation", type=Path, default=home / ".local/state/radiology-workbench/gpu-pool")
    sub = parser.add_subparsers(dest="command", required=True)
    first = sub.add_parser("prepare")
    first.add_argument("--python-env", default="rw-server")
    first.add_argument("--node-env", help="conda environment with Node, when npm is not on PATH (default rwnode)")
    sub.add_parser("deploy").add_argument("tag")
    sub.add_parser("rollback")
    args = parser.parse_args()
    return {"prepare": prepare, "deploy": deploy, "rollback": rollback}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
