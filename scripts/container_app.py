"""Container entry point (OPS-01): validate the config, then run `app.main:app` with uvicorn.

The SPA is mounted by `app.main.create_app` (STATIC_ROOT). This wrapper exists so that invalid
config (e.g. an empty ALLOWED_DATA_ROOTS in container mode, OPS-04) exits with one clean line
instead of an import-time traceback.

    python scripts/container_app.py      # HOST, PORT, LOG_LEVEL from env (OPS-03)
"""

from __future__ import annotations

import sys

from pydantic import ValidationError

from app.config import get_settings


def main() -> None:
    try:
        settings = get_settings()  # invalid config stops here, before binding the port
    except ValidationError as e:
        sys.exit("refusing to start: " + "; ".join(err["msg"] for err in e.errors()))

    import uvicorn

    from app.main import app

    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level)


if __name__ == "__main__":
    main()
