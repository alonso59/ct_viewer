#!/usr/bin/env python3
"""Native deployment: run the app from conda environments, without a container.

    python3 scripts/rw-native.py prepare                 # release + environment + smoke, no restart
    python3 scripts/rw-native.py deploy TAG              # switch production; restores it on failure
    python3 scripts/rw-native.py rollback                # back to the release before the last deploy
    python3 scripts/rw-native.py run [TAG]               # a release in the foreground, no systemd
    python3 scripts/rw-native.py start|stop|status|log|credential   # the app as a scheduler job

`run` inside a scheduler job also writes the connection file and a per-job session code.
`start` and the commands after it run on a login node and only talk to the scheduler; their
settings are `config/app-job.env` in the state folder (TIME, CPUS, MEMORY, and where the site
needs them ACCOUNT, PARTITION, QOS; optional TAG, BIND, DEPLOYMENT, RUNNER_PYTHON).

No sudo: conda environments and systemd user units only. Node builds the web app (`--node-env`, or
`npm` on PATH) and never runs in production. Standard library only, so any Python 3 can start it.
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import sqlite3
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
JOB_NAME = "rw-app"
CONNECTION, CREDENTIAL = "app-job.json", "app-job.credential"
NAME = r"[A-Za-z0-9][A-Za-z0-9_.:-]*"
JOB_SETTINGS = {
    "ACCOUNT": NAME,
    "PARTITION": NAME,
    "QOS": NAME,
    "TIME": r"[0-9][0-9:-]*",
    "CPUS": r"[1-9][0-9]{0,3}",
    "MEMORY": r"[1-9][0-9]*[MG]",
}


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
LimitNOFILE=1048576
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
    port = read_env(state / "config/runtime.env")["PORT"]
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


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for raw in path.read_text().splitlines():
        key, found, value = raw.strip().partition("=")
        if found and key and not key.startswith("#"):
            values[key] = value.strip().strip("\"'")
    return values


def storage_problem(folder: Path) -> str:
    """Why `folder` cannot hold the app's locks and SQLite files; empty when it can."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = Path(tempfile.mkdtemp(prefix=".rw-probe-", dir=folder))
    except OSError as exc:
        return str(exc)
    try:
        with (probe / "lock").open("w") as held, (probe / "lock").open("w") as second:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                return "file locks are not enforced"
        db = sqlite3.connect(probe / "probe.sqlite")
        try:
            if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                return "SQLite cannot use write-ahead logging"
            db.execute("CREATE TABLE probe (value)")
            db.execute("INSERT INTO probe VALUES (1)")
            db.commit()
        finally:
            db.close()
    except (OSError, sqlite3.Error) as exc:
        return str(exc)
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    return ""


def free_port(host: str, first: int) -> int:
    for port in range(first, min(first + 100, 65536)):
        with socket.socket() as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    raise SystemExit(f"no free port from {first}")


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_name(path.name + ".next")
    temporary.unlink(missing_ok=True)
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        handle.write(text)
    temporary.replace(path)


def job_settings(state: Path) -> dict[str, str]:
    path = state / "config/app-job.env"
    config = {"CPUS": "4", "MEMORY": "16G", **(read_env(path) if path.exists() else {})}
    for key, pattern in JOB_SETTINGS.items():
        if key in config and not re.fullmatch(pattern, config[key]):
            raise SystemExit(f"{path}: invalid {key}")
    if config.get("BIND", "loopback") not in ("loopback", "node"):
        raise SystemExit(f"{path}: BIND is loopback or node")
    return config


def release_of(state: Path, tag: str | None) -> tuple[Path, dict[str, Any]]:
    current = state / "config/release.json"
    if tag is None and current.exists():
        tag = json.loads(current.read_text()).get("tag")
    if tag is None:
        raise SystemExit("name a release: TAG in config/app-job.env, or `run TAG`")
    release = (state / "releases" / tag).resolve()
    try:
        return release, json.loads((release / "release.json").read_text())
    except OSError:
        raise SystemExit(f"{release} is not a prepared release") from None


def run_release(args: argparse.Namespace) -> int:
    """App, and runner when one is configured, as foreground children until one ends or a signal."""
    state: Path = args.state
    config = job_settings(state)
    try:
        runtime = read_env(state / "config/runtime.env")
    except OSError:
        raise SystemExit(f"{state / 'config/runtime.env'} is missing") from None
    release, meta = release_of(state, args.tag or config.get("TAG"))
    prefix = Path(meta["python_env"])
    workspace = Path(runtime.get("WORKSPACE_ROOT") or state / "workspace")
    problem = storage_problem(workspace)
    if problem:
        raise SystemExit(f"refusing to start: {workspace} cannot hold the application state: {problem}")
    job_id = os.environ.get("SLURM_JOB_ID", "")
    bind = args.bind or config.get("BIND", "loopback")
    host = "127.0.0.1" if bind == "loopback" else "0.0.0.0"
    port = int(runtime.get("PORT", "8000"))
    env = {
        **os.environ,
        **runtime,
        **release_env(release),
        "CONTAINER_MODE": "0",
        "STATIC_ROOT": str(release / "static"),
        "HOST_ALLOCATION_ROOT": str(args.allocation.resolve()),
        "HOST": host,
        "PATH": f"{prefix / 'bin'}:/usr/local/bin:/usr/bin:/bin",
    }
    connection, credential = args.job_dir / CONNECTION, args.job_dir / CREDENTIAL
    if job_id:
        # Other users of a compute node reach its ports, so a job never serves without a session.
        port = free_port(host, port)
        write_private(credential, secrets.token_urlsafe(32) + "\n")
        env["SESSION_CREDENTIAL_FILE"] = str(credential)
    env["PORT"] = str(port)
    stopping: list[int] = []
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda received, _frame: stopping.append(received))
    python = str(prefix / "bin/python")
    children = [subprocess.Popen([python, str(release / "scripts/container_app.py")], cwd=release / "backend", env=env)]
    if "DEPLOYMENT" in config:
        children.append(
            subprocess.Popen(
                [
                    config.get("RUNNER_PYTHON", python),
                    str(release / "scripts/rw-runner.py"),
                    "--workspace",
                    str(workspace),
                    "--plugins",
                    str(release / "plugins"),
                    "--deployment",
                    config["DEPLOYMENT"],
                ],
                env=env,
            )
        )
    api, announced = Api(str(port)), not job_id
    try:
        while not stopping and all(child.poll() is None for child in children):
            if not announced:
                try:
                    announced = api.get("/health")["status"] == "ok"
                except (urllib.error.URLError, OSError, ValueError, KeyError):
                    pass
                if announced:
                    end = os.environ.get("SLURM_JOB_END_TIME", "")
                    record = {
                        "job_id": job_id,
                        "node": socket.gethostname().split(".")[0],
                        "port": port,
                        "bind": bind,
                        "tag": meta["tag"],
                        "started": datetime.datetime.now(datetime.UTC).isoformat(),
                        "ends": datetime.datetime.fromtimestamp(int(end), datetime.UTC).isoformat()
                        if end.isdigit()
                        else None,
                    }
                    write_private(connection, json.dumps(record, indent=2) + "\n")
            time.sleep(0.5)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if job_id:
            connection.unlink(missing_ok=True)
            credential.unlink(missing_ok=True)
    return 0 if stopping else max(abs(child.returncode) for child in children) or 1


def app_job() -> tuple[str, str, str, str, str] | None:
    """(id, state, node, elapsed, limit) of the user's newest app job; None when there is none."""
    listed = subprocess.run(
        ["squeue", "--noheader", f"--user={os.getuid()}", f"--name={JOB_NAME}", "--format=%i|%T|%N|%M|%l"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows = [tuple(part.strip() for part in line.split("|")) for line in listed.splitlines() if line.count("|") == 4]
    return max(rows, key=lambda row: int(row[0]), default=None)  # type: ignore[return-value]


def connection_of(job_dir: Path, job: tuple[str, ...] | None) -> dict[str, Any] | None:
    """The running job's connection record. The scheduler is the truth: anything else is deleted."""
    try:
        record = json.loads((job_dir / CONNECTION).read_text())
    except (OSError, ValueError):
        record = None
    if job is not None and job[1] == "RUNNING" and record is not None and record.get("job_id") == job[0]:
        return dict(record)
    if job is None or record is not None:
        (job_dir / CONNECTION).unlink(missing_ok=True)
        (job_dir / CREDENTIAL).unlink(missing_ok=True)
    return None


def print_status(job_dir: Path, job: tuple[str, ...]) -> None:
    identity, state, node, elapsed, limit = job
    print(f"  Job       : {identity}\n  State     : {state}   (elapsed {elapsed} / limit {limit})")
    record = connection_of(job_dir, job)
    if record is None:
        if state == "RUNNING":
            print("  App       : not answering yet (see `log`)")
        return
    target = f"{record['node']}:{record['port']}"
    print(f"  Release   : {record['tag']}\n  Ends      : {record['ends'] or limit}")
    if record["bind"] == "loopback":
        print(f"  Listening : 127.0.0.1:{record['port']} on {node}, reachable only from that node")
        print(f"  Open it   : connect VS Code Remote to {node}, forward port {record['port']} in the Ports")
        print("              panel, then open the forwarded http://localhost:<port> in your browser.")
    else:
        print(f"  Listening : {target}, reachable from the cluster network")
        print(f'  Open it   : VS Code Ports panel -> "Forward a Port" -> {target}, then open the forwarded')
        print("              http://localhost:<port>. HTTP is not encrypted between the login node and")
        print(f"              {node} in this mode.")
    print("  Sign in   : with the session code shown by the `credential` command")


def start_job(args: argparse.Namespace) -> int:
    state: Path = args.state
    job = app_job()
    if job is not None:
        print(f"An app job is already {job[1].lower()}; stop it first.", file=sys.stderr)
        print_status(args.job_dir, job)
        return 1
    connection_of(args.job_dir, None)
    config = job_settings(state)
    if "TIME" not in config:
        raise SystemExit(f"{state / 'config/app-job.env'}: set TIME (the wall time of the app job)")
    release, meta = release_of(state, config.get("TAG"))
    (state / "logs").mkdir(exist_ok=True)
    flags = {"ACCOUNT": "account", "PARTITION": "partition", "QOS": "qos"}
    submitted = subprocess.run(
        [
            "sbatch",
            "--parsable",
            "--export=NONE",
            f"--job-name={JOB_NAME}",
            "--nodes=1",
            "--ntasks=1",
            f"--cpus-per-task={config['CPUS']}",
            f"--mem={config['MEMORY']}",
            f"--time={config['TIME']}",
            "--signal=B:TERM@120",
            f"--output={state / 'logs' / (JOB_NAME + '-%j.log')}",
            *[f"--{flag}={config[key]}" for key, flag in flags.items() if key in config],
            str(Path(__file__).resolve().with_name("rw-app.sbatch")),
            "_run",
            str(Path(meta["python_env"]) / "bin/python"),
            str(Path(__file__).resolve()),
            str(state),
            str(args.job_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    identity = submitted.stdout.strip().split(";")[0]
    if submitted.returncode or not identity.isdigit():
        raise SystemExit(f"The scheduler refused the job: {submitted.stderr.strip() or submitted.stdout.strip()}")
    print(f"Submitted job {identity} ({release.name}); waiting for a node and for the app. Ctrl-C leaves it queued.")
    deadline = None
    while True:
        job = app_job()
        if job is None or job[0] != identity or job[1] not in ("PENDING", "CONFIGURING", "RUNNING"):
            log = state / "logs" / f"{JOB_NAME}-{identity}.log"
            raise SystemExit(f"Job {identity} ended early ({job[1] if job else 'gone'}); see {log}")
        if job[1] == "RUNNING":
            deadline = deadline or time.monotonic() + args.wait
            if connection_of(args.job_dir, job) is not None or time.monotonic() > deadline:
                break
        time.sleep(args.poll)
    print_status(args.job_dir, job)
    return 0


def stop_job(args: argparse.Namespace) -> int:
    job = app_job()
    if job is None:
        print("No app job is queued or running.")
    else:
        run("scancel", job[0])
        while (current := app_job()) is not None and current[0] == job[0]:
            time.sleep(args.poll)
        print(f"Stopped job {job[0]}. Compute jobs it submitted keep running.")
    connection_of(args.job_dir, None)
    return 0


def status_job(args: argparse.Namespace) -> int:
    job = app_job()
    if job is None:
        connection_of(args.job_dir, None)
        print("No app job is queued or running (start one with `start`).")
    else:
        print_status(args.job_dir, job)
    return 0


def log_job(args: argparse.Namespace) -> int:
    logs = sorted((args.state / "logs").glob(f"{JOB_NAME}-*.log"), key=lambda path: path.stat().st_mtime)
    if not logs:
        raise SystemExit("No app job log yet.")
    os.execvp("tail", ["tail", "-n", "100", *(["-f"] if args.follow else []), str(logs[-1])])


def credential_job(args: argparse.Namespace) -> int:
    if connection_of(args.job_dir, app_job()) is None:
        raise SystemExit("No app job is running and answering.")
    sys.stdout.write((args.job_dir / CREDENTIAL).read_text())
    return 0


def main() -> int:
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", type=Path, default=home / ".local/share/radiology-workbench")
    parser.add_argument("--allocation", type=Path, default=home / ".local/state/radiology-workbench/gpu-pool")
    parser.add_argument("--job-dir", type=Path, default=home / ".local/state/radiology-workbench")
    parser.add_argument("--poll", type=float, default=5.0, help=argparse.SUPPRESS)
    parser.add_argument("--wait", type=float, default=180.0, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    first = sub.add_parser("prepare")
    first.add_argument("--python-env", default="rw-server")
    first.add_argument("--node-env", help="conda environment with Node, when npm is not on PATH (default rwnode)")
    sub.add_parser("deploy").add_argument("tag")
    sub.add_parser("rollback")
    foreground = sub.add_parser("run")
    foreground.add_argument("tag", nargs="?")
    foreground.add_argument("--bind", choices=["loopback", "node"], help="default: BIND, else loopback")
    for name in ("start", "stop", "status", "log", "credential"):
        sub.add_parser(name)
    sub.choices["log"].add_argument("-f", "--follow", action="store_true")
    args = parser.parse_args()
    commands = {
        "prepare": prepare,
        "deploy": deploy,
        "rollback": rollback,
        "run": run_release,
        "start": start_job,
        "stop": stop_job,
        "status": status_job,
        "log": log_job,
        "credential": credential_job,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
