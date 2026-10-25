"""Container entry point: validate the config, then run `app.main:app` with uvicorn.

Invalid config (e.g. an empty ALLOWED_DATA_ROOTS in container mode) exits with one clean line
instead of an import-time traceback.

    python scripts/container_app.py      # HOST, PORT, LOG_LEVEL from env
"""

from __future__ import annotations

import sys

from pydantic import ValidationError

from app.config import get_settings


def main() -> None:
    try:
        settings = get_settings()  # invalid config stops here, before binding the port
    except ValidationError as e:
        msgs = (str(err["msg"]).removeprefix("Value error, ") for err in e.errors())
        sys.exit("refusing to start: " + "; ".join(msgs))

    import uvicorn

    from app.main import app

    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level)


if __name__ == "__main__":
    main()
