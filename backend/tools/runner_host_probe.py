"""CLI entry point for the host containment probe."""

import shutil
import subprocess

from plugins.runner.probe import REQUIRED_CHECKS, main, run_probe

__all__ = ["REQUIRED_CHECKS", "main", "run_probe", "shutil", "subprocess"]

if __name__ == "__main__":
    raise SystemExit(main())
