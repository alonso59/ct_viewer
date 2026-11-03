"""One command line → name, positional words and `-option value` pairs.

Words split on blanks; `"…"` and `{…}` group a word. Variables, `[cmd]` substitution and control
flow belong to the script language (CTF-07) and are not read here."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.errors import ValidationProblem

LINE_MAX = 4000
_OPTION = re.compile(r"^-[A-Za-z][A-Za-z0-9_-]*$")
FLAG = "true"  # an option given alone


@dataclass
class Line:
    name: str
    args: list[str] = field(default_factory=list)
    options: dict[str, str] = field(default_factory=dict)


def words(text: str) -> list[str]:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == '"':
            end = text.find('"', i + 1)
            if end < 0:
                raise ValidationProblem("Missing closing quote")
            out.append(text[i + 1 : end])
            i = end + 1
        elif c == "{":
            depth, j = 1, i + 1
            while j < n and depth:
                depth += {"{": 1, "}": -1}.get(text[j], 0)
                j += 1
            if depth:
                raise ValidationProblem("Missing closing brace")
            out.append(text[i + 1 : j - 1])
            i = j
        else:
            j = i
            while j < n and not text[j].isspace():
                j += 1
            out.append(text[i:j])
            i = j
    return out


def parse(text: str) -> Line:
    if len(text) > LINE_MAX:
        raise ValidationProblem(f"A command line has at most {LINE_MAX} characters")
    ws = words(text.strip().removeprefix("/"))
    if not ws:
        raise ValidationProblem("Type a command; `help` lists them")
    line = Line(ws[0])
    i = 1
    while i < len(ws):
        w = ws[i]
        if _OPTION.match(w):
            key = w[1:]
            if key in line.options:
                raise ValidationProblem(f"Option -{key} is given twice")
            nxt = ws[i + 1] if i + 1 < len(ws) else None
            if nxt is None or _OPTION.match(nxt):
                line.options[key] = FLAG
                i += 1
            else:
                line.options[key] = nxt
                i += 2
        else:
            line.args.append(w)
            i += 1
    return line
