"""OPS-19: process-local restrictions without namespaces, services or privileges."""

from __future__ import annotations

import argparse
import ctypes
import errno
import os
import platform
import sys
from pathlib import Path

WRITE = 1 << 1
TRUNCATE = 1 << 14
MUTATIONS = WRITE | sum(1 << bit for bit in range(4, 15))


class Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class Filter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    ]


class Program(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(Filter))]


def checked(result: int, operation: str) -> int:
    if result < 0:
        code = ctypes.get_errno()
        raise OSError(code, f"{operation}: {os.strerror(code)}")
    return result


def abi() -> int:
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise OSError(errno.ENOTSUP, "unprivileged sandbox requires Linux x86_64/aarch64")
    libc = ctypes.CDLL(None, use_errno=True)
    return checked(libc.syscall(444, 0, 0, 1), "Landlock ABI")


def restrict_writes(writable: list[Path], devices: list[Path]) -> None:
    if abi() < 3:
        raise OSError(errno.ENOTSUP, "Landlock ABI 3 is required for truncate protection")
    libc = ctypes.CDLL(None, use_errno=True)
    checked(libc.prctl(38, 1, 0, 0, 0), "no_new_privs")
    attr = Ruleset(MUTATIONS)
    ruleset = checked(libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0), "create Landlock ruleset")
    try:
        paths = [(path, MUTATIONS if path.is_dir() else WRITE | TRUNCATE) for path in [*writable, *devices]]
        # Native runtimes name threads through procfs. Permit only this process;
        # descendant/foreign PID directories and procfs control files stay denied.
        paths += [
            (Path(f"/proc/{os.getpid()}/task"), WRITE | TRUNCATE),
            (Path(f"/proc/{os.getpid()}/comm"), WRITE | TRUNCATE),
        ]
        for path, rights in paths:
            descriptor = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(rights, descriptor)
                checked(libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0), "add Landlock path")
            finally:
                os.close(descriptor)
        checked(libc.syscall(446, ruleset, 0), "restrict Landlock process")
    finally:
        os.close(ruleset)


def restrict_network() -> None:
    machine = platform.machine()
    if machine == "x86_64":
        arch, socket_nr, pair_nr, forbidden = 0xC000003E, 41, 53, (101, 311, 321, 425, 438)
    elif machine == "aarch64":
        arch, socket_nr, pair_nr, forbidden = 0xC00000B7, 198, 199, (117, 271, 280, 425, 438)
    else:
        raise OSError(errno.ENOTSUP, "unsupported seccomp architecture")
    deny = 0x00050000 | errno.EPERM
    allow = 0x7FFF0000
    instructions = [
        (0x20, 0, 0, 4),
        (0x15, 1, 0, arch),
        (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0),
    ]
    if machine == "x86_64":
        instructions.extend([(0x45, 0, 1, 0x40000000), (0x06, 0, 0, deny)])
    for number in forbidden:
        instructions.extend([(0x15, 0, 1, number), (0x06, 0, 0, deny)])
    for number in (socket_nr, pair_nr):
        instructions.extend(
            [
                (0x15, 0, 4, number),
                (0x20, 0, 0, 16),
                (0x15, 1, 0, 1),
                (0x06, 0, 0, deny),
                (0x06, 0, 0, allow),
            ]
        )
    instructions.append((0x06, 0, 0, allow))
    filters = (Filter * len(instructions))(*(Filter(*value) for value in instructions))
    program = Program(len(filters), filters)
    libc = ctypes.CDLL(None, use_errno=True)
    checked(libc.prctl(38, 1, 0, 0, 0), "no_new_privs")
    checked(libc.prctl(22, 2, ctypes.byref(program), 0, 0), "seccomp filter")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="append", default=[])
    parser.add_argument("--device", action="append", default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("an executable is required")
    for value in args.write:
        path = Path(value)
        if not path.is_absolute() or path.resolve() != path or not path.is_dir() or path.parent == path:
            parser.error("write roots must be existing canonical, non-root absolute directories")
    try:
        restrict_writes([Path(value) for value in args.write], [Path(value) for value in args.device])
        restrict_network()
    except OSError as exc:
        parser.exit(2, f"sandbox unavailable: {exc}\n")
    os.execvpe(command[0], command, {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
