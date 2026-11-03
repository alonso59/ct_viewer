"""A command's evaluated words → name, positional words and `-option value` pairs.

Splitting text into words, quoting and substitution belong to the script language (`lang`)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.errors import ValidationProblem

_OPTION = re.compile(r"^-[A-Za-z][A-Za-z0-9_-]*$")
FLAG = "true"  # an option given alone


@dataclass
class Line:
    name: str
    args: list[str] = field(default_factory=list)
    options: dict[str, str] = field(default_factory=dict)


def options_of(ws: list[str]) -> Line:
    line = Line(ws[0].removeprefix("/"))
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
