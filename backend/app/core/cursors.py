"""Generation-fenced cursors for durable source inventories and plans."""

from __future__ import annotations

import base64
import json

from app.core.errors import JobConflict, ValidationProblem


def encode_cursor(generation: str, offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps([generation, offset]).encode()).decode()


def decode_cursor(cursor: str | None, generation: str) -> int:
    if cursor is None:
        return 0
    try:
        payload = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if not isinstance(payload, list) or len(payload) != 2:
            raise ValueError
        previous, offset = payload
        if not isinstance(previous, str) or type(offset) is not int or not 0 <= offset < 2**63:
            raise ValueError
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValidationProblem("Invalid source listing cursor") from exc
    if previous != generation:
        raise JobConflict("Listing generation changed; reload its first page")
    return offset
