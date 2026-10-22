"""OPS-19: real, GPU-free Landlock/seccomp effects and inheritance."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SANDBOX = REPO / "plugins/runner/sandbox.py"


def sandbox(tmp_path: Path, script: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    writable = tmp_path / "writable"
    writable.mkdir()
    source = tmp_path / "source"
    source.write_text("original")
    (writable / "escape").symlink_to(source)
    result = subprocess.run(
        [
            sys.executable,
            str(SANDBOX),
            "--write",
            str(writable),
            "--",
            sys.executable,
            "-c",
            script,
            str(source),
            str(writable),
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return result, source


@pytest.mark.parametrize(
    "operation",
    [
        "source.write_text('changed')",
        "source.unlink()",
        "source.rename(root / 'moved')",
        "os.truncate(source, 0)",
        "(root / 'escape').write_text('changed')",
        "(source.parent / 'outside').write_text('changed')",
        "os.link(source, root / 'hardlink')",
    ],
)
def test_outside_writes_are_denied(tmp_path: Path, operation: str) -> None:
    result, source = sandbox(
        tmp_path,
        f"""
import errno, os, sys
from pathlib import Path
source, root = map(Path, sys.argv[1:])
assert source.read_text() == 'original'
try:
    {operation}
except OSError as error:
    assert error.errno in (errno.EACCES, errno.EPERM, errno.EXDEV), error
else:
    raise AssertionError('outside mutation was permitted')
(root / 'ok').write_text('allowed')
""",
    )
    assert result.returncode == 0, result.stderr
    assert source.read_text() == "original"
    assert (tmp_path / "writable/ok").read_text() == "allowed"


@pytest.mark.parametrize(
    "family,kind",
    [
        ("AF_INET", "SOCK_STREAM"),
        ("AF_INET6", "SOCK_STREAM"),
        ("AF_INET", "SOCK_DGRAM"),
        ("AF_NETLINK", "SOCK_RAW"),
    ],
)
def test_nonlocal_network_sockets_are_denied(tmp_path: Path, family: str, kind: str) -> None:
    result, _source = sandbox(
        tmp_path,
        f"""
import errno, socket
try:
    connection = socket.socket(socket.{family}, socket.{kind})
except OSError as error:
    assert error.errno == errno.EPERM, error
else:
    connection.close()
    raise AssertionError('network socket was permitted')
""",
    )
    assert result.returncode == 0, result.stderr


def test_local_ipc_and_descendant_confinement(tmp_path: Path) -> None:
    result, _source = sandbox(
        tmp_path,
        """
import json, socket, subprocess, sys
from pathlib import Path
source, root = sys.argv[1:]
left, right = socket.socketpair()
left.send(b'ok'); assert right.recv(2) == b'ok'
left.close(); right.close()
child = subprocess.run([sys.executable, '-c',
    "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('changed')", source],
    capture_output=True, start_new_session=True, timeout=2)
assert child.returncode != 0, 'setsid child escaped write restriction'
Path(root, 'ok').write_text('allowed')
print(json.dumps({'ipc': True, 'descendants': True}))
""",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"ipc": True, "descendants": True}


def test_native_thread_names_work_without_proc_fd_source_write_escape(tmp_path: Path) -> None:
    result, source = sandbox(
        tmp_path,
        """
import os, subprocess, sys, threading
from pathlib import Path
source, root = map(Path, sys.argv[1:])
def rename():
    name = Path(f'/proc/self/task/{threading.get_native_id()}/comm')
    name.write_text('rw-native-test')
    assert name.read_text().strip() == 'rw-native-test'
rename()
thread = threading.Thread(target=rename)
thread.start(); thread.join()
child = subprocess.run([sys.executable, '-c',
    "from pathlib import Path; Path('/proc/self/comm').write_text('rw-child-test')"],
    capture_output=True)
assert child.returncode != 0, 'procfs exception escaped the original process'
descriptor = os.open(source, os.O_RDONLY)
try:
    Path(f'/proc/self/fd/{descriptor}').write_text('changed')
except PermissionError:
    pass
else:
    raise AssertionError('procfs descriptor bypassed source write protection')
finally:
    os.close(descriptor)
""",
    )
    assert result.returncode == 0, result.stderr
    assert source.read_text() == "original"
