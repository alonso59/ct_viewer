"""OPS-09 (AUD-A4-02): `scripts/udocker-run.sh --dry-run` runs the command compose would run.

The compose side is read from `docker-compose.yml` itself (its `environment:` and `volumes:`
lines, with compose's `${VAR}`, `${VAR:-default}`, `${VAR:?error}` interpolation) and compared
with the udocker arguments for the same `.env`. Differences by design (DEPLOYMENT.md): `HOST`
and `PORT` (udocker shares the host network), `:ro` flags (udocker has none; the app enforces
R1), `user`, `ports`, `restart`. No Docker or udocker is needed."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "udocker-run.sh"
COMPOSE = REPO / "docker-compose.yml"
BY_DESIGN = {"HOST", "PORT"}


def interpolate(text: str, env: dict[str, str]) -> str:
    """Compose variable substitution, nested defaults included."""
    out, i = "", 0
    while i < len(text):
        if text.startswith("${", i):
            depth, j = 1, i + 2
            while depth:
                depth += {"{": 1, "}": -1}.get(text[j], 0)
                j += 1
            expr = text[i + 2 : j - 1]
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)(?:(:-|:\?)(.*))?$", expr, re.S)
            assert m, expr
            name, op, arg = m.groups()
            val = env.get(name, "")
            if not val and op == ":-":
                val = interpolate(arg, env)
            elif not val and op == ":?":
                raise ValueError(arg)
            out, i = out + val, j
        else:
            out, i = out + text[i], i + 1
    return out


def compose_side(env: dict[str, str], env_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """(`environment:` overrides, volume target → source) as compose resolves them."""
    lines = COMPOSE.read_text(encoding="utf-8").splitlines()
    environment: dict[str, str] = {}
    volumes: dict[str, str] = {}
    section = ""
    for line in lines:
        code = re.sub(r"\s+#.*$", "", line)
        if m := re.match(r"^    (\w+):", code):
            section = m.group(1)
            continue
        if section == "environment" and (m := re.match(r"^      ([A-Z_]+):\s*(.+)$", code)):
            environment[m.group(1)] = interpolate(m.group(2).strip().strip('"'), env)
        elif section == "volumes" and (m := re.match(r"^      - (.+)$", code)):
            spec = interpolate(m.group(1).strip(), env).removesuffix(":ro")
            src, dst = spec.rsplit(":", 1)
            if not src.startswith("/"):
                src = str(env_dir / src.removeprefix("./"))
            volumes[dst] = src
    return environment, volumes


def udocker_side(env_file: Path) -> tuple[dict[str, str], dict[str, str], list[str]]:
    run_env = {**os.environ, "UDOCKER": "udocker", "RW_CONTAINER": "rw"}
    out = subprocess.run(
        ["bash", str(SCRIPT), "--env-file", str(env_file), "--dry-run"],
        capture_output=True,
        text=True,
        env=run_env,
        check=True,
    ).stdout
    args = shlex.split(out)
    assert args[:2] == ["udocker", "run"] and args[-1] == "rw"
    env: dict[str, str] = {}
    volumes: dict[str, str] = {}
    for a in args[2:-1]:
        if a.startswith("--env="):
            k, v = a.removeprefix("--env=").split("=", 1)
            env[k] = v  # the fixed values come last and win, as in the script
        elif a.startswith("--volume="):
            src, dst = a.removeprefix("--volume=").rsplit(":", 1)
            volumes[dst] = src
    return env, volumes, args


def write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")


CASES = {
    "minimal": {"DATA_HOST": "/data/ct"},
    "derived and overrides": {
        "DATA_HOST": "/data/ct",
        "DERIVED_HOST": "/scratch/rw-derived",
        "WORKSPACE_HOST": "./ws",
        "PLUGINS_HOST": "/opt/rw-plugins",
        "ALLOWED_DATA_ROOTS": "/data/ct",
        "PORT": "8123",
        "PUBLIC_BASE_URL": "http://localhost:9000",
        "CACHE_MAX_GB": "5",
        "LOG_LEVEL": "debug",
    },
}


@pytest.mark.parametrize("values", CASES.values(), ids=list(CASES))
def test_dry_run_matches_compose(tmp_path: Path, values: dict[str, str]) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file, values)
    ud_env, ud_volumes, _ = udocker_side(env_file)
    c_env, c_volumes = compose_side(values, tmp_path)

    # `environment:` overrides: same keys and values, apart from the host-network pair
    assert {k: v for k, v in c_env.items() if k not in BY_DESIGN} == {
        k: ud_env[k] for k in c_env if k not in BY_DESIGN
    }
    assert ud_env["CONTAINER_MODE"] == "1"  # set by the image under Docker (Dockerfile ENV)
    assert ud_env["PORT"] == values.get("PORT", "8000")
    # `env_file:`: every other .env key reaches the container
    for k, v in values.items():
        if k not in c_env:
            assert ud_env[k] == v, k
    # Same mounts at the same container paths (compose's `:ro` is enforced by the app there)
    assert ud_volumes == c_volumes


def test_missing_data_host_is_refused_like_compose(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    write_env(env_file, {"PORT": "8000"})
    with pytest.raises(ValueError, match="set DATA_HOST"):
        compose_side({"PORT": "8000"}, tmp_path)
    r = subprocess.run(
        ["bash", str(SCRIPT), "--env-file", str(env_file), "--dry-run"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2 and "DATA_HOST" in r.stderr
