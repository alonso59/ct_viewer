"""Launch allowlisted native CLIs in independent, process-local sandboxes."""

from __future__ import annotations

import json
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

MAX_REQUEST = 32768


def receive(connection: socket.socket) -> dict[str, Any]:
    data = bytearray()
    while len(data) <= MAX_REQUEST:
        chunk = connection.recv(4096)
        if not chunk:
            raise ValueError("incomplete native request")
        data.extend(chunk)
        if len(data) > MAX_REQUEST:
            raise ValueError("native request too large")
        if b"\n" in chunk:
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("invalid native request")
            return value
    raise ValueError("native request too large")


def terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)


class Broker:
    def __init__(
        self,
        record: dict[str, Any],
        environment: dict[str, str],
        output: Callable[[Any], None],
    ) -> None:
        self.record, self.environment, self.output = record, environment, output
        self.path = Path(record["runtime_alias"]) / "native.sock"
        self.stopping = threading.Event()
        self.slots = threading.BoundedSemaphore(4)
        self.handlers: list[threading.Thread] = []
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.path))
        self.path.chmod(0o600)
        self.listener.listen(4)
        self.listener.settimeout(0.1)
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def request(self, connection: socket.socket) -> tuple[list[str], dict[str, str]]:
        pid, uid, _gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid() or (
            f"rw-seg-{self.record['attempt']}.service" not in Path(f"/proc/{pid}/cgroup").read_text()
        ):
            raise ValueError("native caller is outside the owned attempt")
        request = receive(connection)
        command, visibility = request.get("command"), request.get("gpus")
        if (
            request.get("attempt") != self.record["attempt"]
            or not isinstance(command, list)
            or not command
            or any(not isinstance(value, str) or "\0" in value for value in command)
            or command[0] not in self.record["native_commands"]
            or not isinstance(visibility, str)
            or not visibility
            or len(visibility.split(",")) != len(set(visibility.split(",")))
            or not set(visibility.split(",")).issubset(self.record["gpus"])
        ):
            raise ValueError("unapproved native command or GPU selection")
        executable = Path(sys.executable).parent / command[0]
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("native executable unavailable in configured environment")
        sandbox = Path(__file__).with_name("sandbox.py")
        argv = [sys.executable, "-I", str(sandbox)]
        for path in self.record["write_roots"]:
            argv += ["--write", path]
        for path in self.record["devices"]:
            argv += ["--device", path]
        argv += ["--", str(executable), *command[1:]]
        return argv, {**self.environment, "CUDA_VISIBLE_DEVICES": visibility}

    def handle(self, connection: socket.socket) -> None:
        process: subprocess.Popen[bytes] | None = None
        reader: threading.Thread | None = None
        try:
            connection.settimeout(5)
            command, environment = self.request(connection)
            process = subprocess.Popen(
                command,
                env=environment,
                cwd=self.record["cwd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                bufsize=0,
            )
            reader = threading.Thread(target=self.output, args=(process.stdout,), daemon=True)
            reader.start()
            while process.poll() is None:
                readable, _, _ = select.select([connection], [], [], 0.1)
                if self.stopping.is_set() or (readable and connection.recv(1, socket.MSG_PEEK) == b""):
                    terminate(process)
                    break
            reader.join(timeout=2)
            connection.sendall(json.dumps({"code": process.returncode}).encode() + b"\n")
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            try:
                connection.sendall(json.dumps({"code": 125, "error": str(exc)}).encode() + b"\n")
            except OSError:
                pass
        finally:
            if process is not None:
                terminate(process)
                if reader is not None:
                    reader.join(timeout=2)
                if process.stdout is not None:
                    process.stdout.close()
            connection.close()
            self.slots.release()

    def serve(self) -> None:
        while not self.stopping.is_set():
            try:
                connection, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self.handlers = [handler for handler in self.handlers if handler.is_alive()]
            if not self.slots.acquire(blocking=False):
                connection.close()
                continue
            handler = threading.Thread(target=self.handle, args=(connection,), daemon=True)
            self.handlers.append(handler)
            handler.start()

    def close(self) -> None:
        self.stopping.set()
        self.listener.close()
        self.thread.join(timeout=1)
        for handler in self.handlers:
            handler.join(timeout=8)
        self.path.unlink(missing_ok=True)


def client() -> int:
    request = {
        "attempt": os.environ["RW_NATIVE_ATTEMPT"],
        "gpus": os.environ["CUDA_VISIBLE_DEVICES"],
        "command": sys.argv[1:],
    }
    data = json.dumps(request).encode() + b"\n"
    if len(data) > MAX_REQUEST:
        raise ValueError("native request too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(os.environ["RW_NATIVE_SOCKET"])
        connection.sendall(data)
        response = receive(connection)
    if response.get("error"):
        print(response["error"], file=sys.stderr)
    return int(response["code"])


if __name__ == "__main__":
    raise SystemExit(client())
