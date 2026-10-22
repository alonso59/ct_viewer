"""OPS-19: the launch boundary accepts only its generation, commands and GPU subset."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

import pytest
from plugins.runner.native import Broker, receive


@pytest.mark.parametrize(
    "change",
    [
        {"attempt": "stale"},
        {"command": ["python", "-c", "print('unapproved')"]},
        {"command": ["/bin/sh", "-c", "true"]},
        {"gpus": "GPU-outside"},
        {"gpus": "GPU-test,GPU-test"},
        {"command": ["nnUNetv2_predict", "\0"]},
    ],
)
def test_unapproved_native_launches_are_refused(
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
) -> None:
    broker = object.__new__(Broker)
    broker.record = {
        "attempt": "a" * 32,
        "gpus": ["GPU-test"],
        "native_commands": ["nnUNetv2_predict"],
    }
    original_read = Path.read_text

    def cgroup(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == Path(f"/proc/{os.getpid()}/cgroup"):
            return f"0::/user.slice/rw-seg-{broker.record['attempt']}.service"
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", cgroup)
    request = {"attempt": "a" * 32, "command": ["nnUNetv2_predict"], "gpus": "GPU-test", **change}
    left, right = socket.socketpair()
    with left, right:
        right.sendall(json.dumps(request).encode() + b"\n")
        with pytest.raises(ValueError, match="unapproved"):
            broker.request(left)


def test_native_launch_from_outside_the_owned_cgroup_is_refused() -> None:
    broker = object.__new__(Broker)
    broker.record = {"attempt": "b" * 32}
    left, right = socket.socketpair()
    with left, right, pytest.raises(ValueError, match="outside the owned attempt"):
        broker.request(left)


def test_oversized_native_message_is_refused_before_parsing() -> None:
    left, right = socket.socketpair()
    with left, right:
        right.sendall(b" " * 32769 + b"\n")
        with pytest.raises(ValueError, match="too large"):
            receive(left)
