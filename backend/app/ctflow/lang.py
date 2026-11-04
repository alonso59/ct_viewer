"""The CTFlow script language (CTF-07): a deliberately small, Tcl-like subset.

Words, `"…"` (substituted), `{…}` (literal), `$var`, `[cmd]`, `;`/newline separated commands and
`#` comments. Built-ins: set, unset, incr, puts, if/elseif/else, while, foreach, proc, return,
break, continue, global, catch, source, expr, list, llength, lindex, lrange, lappend, join.
Everything else is a CTFlow command, run by the caller's `call`.

There is no eval of arbitrary strings, no file, environment, process or network access: the only
way out of the interpreter is `call` (registered commands) and `source` (the script library).
Limits bound steps, nesting, values, lists and child starts; every step yields to the event loop
so one script never blocks the API process (BE-01).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.errors import Problem


@dataclass(frozen=True)
class Limits:
    steps: int = 20_000  # commands evaluated per request
    depth: int = 64  # nested scripts and procedure calls
    value_chars: int = 1_000_000
    list_items: int = 10_000
    starts: int = 200  # runs or operations a request may start
    procs: int = 200


LIMITS = Limits()


class ScriptError(Exception):
    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.message, self.line = message, line


class _Return(Exception):
    def __init__(self, value: str) -> None:
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


# --- parsing ---------------------------------------------------------------------------------


@dataclass
class Var:
    name: str


@dataclass
class Sub:
    script: str


Part = str | Var | Sub


@dataclass
class Word:
    parts: list[Part]


@dataclass
class Command:
    words: list[Word]
    line: int


_NAME = re.compile(r"[A-Za-z0-9_]+")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r"}


def _matching(text: str, i: int) -> int:
    """Index just past the `{…}` or `[…]` opening at `i` (nested braces, brackets, quotes)."""
    opener = text[i]
    closer = "}" if opener == "{" else "]"
    depth, j, n = 1, i + 1, len(text)
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if opener == "[" and c == "{":
            j = _matching(text, j)
            continue
        if opener == "[" and c == '"':
            end = j + 1
            while end < n and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            j = end + 1
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise ScriptError(f"missing close-{'brace' if opener == '{' else 'bracket'}")


def _subst_parts(text: str, i: int, stop: Callable[[str], bool]) -> tuple[list[Part], int]:
    """Parts of a substituted word from `i` up to a `stop` character (not consumed)."""
    parts: list[Part] = []
    buf: list[str] = []
    n = len(text)

    def flush() -> None:
        if buf:
            parts.append("".join(buf))
            buf.clear()

    while i < n and not stop(text[i]):
        c = text[i]
        if c == "\\" and i + 1 < n:
            nxt = text[i + 1]
            buf.append(" " if nxt == "\n" else _ESCAPES.get(nxt, nxt))
            i += 2
        elif c == "$":
            if text.startswith("${", i):
                end = text.find("}", i + 2)
                if end < 0:
                    raise ScriptError("missing close-brace for variable name")
                flush()
                parts.append(Var(text[i + 2 : end]))
                i = end + 1
            elif (m := _NAME.match(text, i + 1)) is not None:
                flush()
                parts.append(Var(m.group(0)))
                i = m.end()
            else:
                buf.append("$")
                i += 1
        elif c == "[":
            end = _matching(text, i)
            flush()
            parts.append(Sub(text[i + 1 : end - 1]))
            i = end
        else:
            buf.append(c)
            i += 1
    flush()
    return parts, i


def parse_script(text: str) -> list[Command]:
    commands: list[Command] = []
    i, n = 0, len(text)
    while i < n:
        while i < n and (text[i].isspace() or text[i] == ";"):
            i += 1
        if i >= n:
            break
        line = text.count("\n", 0, i) + 1
        if text[i] == "#":
            end = text.find("\n", i)
            i = n if end < 0 else end + 1
            continue
        words: list[Word] = []
        while i < n and text[i] not in "\n;":
            c = text[i]
            if c in " \t\r":
                i += 1
                continue
            if c == "\\" and i + 1 < n and text[i + 1] == "\n":
                i += 2
                continue
            if c == "{":
                end = _matching(text, i)
                words.append(Word([text[i + 1 : end - 1]]))
                i = end
            elif c == '"':
                parts, i = _subst_parts(text, i + 1, lambda ch: ch == '"')
                if i >= n:
                    raise ScriptError("missing close-quote", line)
                words.append(Word(parts))
                i += 1
            else:
                parts, i = _subst_parts(text, i, lambda ch: ch.isspace() or ch == ";")
                words.append(Word(parts))
            if i < n and not (text[i].isspace() or text[i] == ";"):
                raise ScriptError("extra characters after close-brace or close-quote", line)
        if words:
            commands.append(Command(words, line))
    return commands


# --- lists -----------------------------------------------------------------------------------

_SPECIAL = re.compile(r'[\s{}\[\]$"\\;]')


def _quote(item: str) -> str:
    if item == "":
        return "{}"
    if not _SPECIAL.search(item):
        return item
    try:
        if _matching("{" + item + "}", 0) == len(item) + 2 and not item.endswith("\\"):
            return "{" + item + "}"
    except ScriptError:
        pass
    return re.sub(r'([\s{}\[\]$"\\;])', r"\\\1", item)


def format_list(items: list[str]) -> str:
    return " ".join(_quote(i) for i in items)


def parse_list(text: str) -> list[str]:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        if text[i] == "{":
            end = _matching(text, i)
            out.append(text[i + 1 : end - 1])
            i = end
        elif text[i] == '"':
            parts, i = _subst_parts(text, i + 1, lambda ch: ch == '"')
            if any(not isinstance(p, str) for p in parts) or i >= n:
                raise ScriptError("malformed list element")
            out.append("".join(p for p in parts if isinstance(p, str)))
            i += 1
        else:
            buf = []
            while i < n and not text[i].isspace():
                if text[i] == "\\" and i + 1 < n:
                    buf.append(_ESCAPES.get(text[i + 1], text[i + 1]))
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            out.append("".join(buf))
    return out


# --- expressions -----------------------------------------------------------------------------

_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+\.\d*(?:[eE][-+]?\d+)?|\d+(?:[eE][-+]?\d+)?|\.\d+)"
    r"|(?P<op>&&|\|\||==|!=|<=|>=|[-+*/%<>!()])"
    r"|(?P<word>[A-Za-z_][A-Za-z0-9_]*))"
)
_BINARY = [["||"], ["&&"], ["==", "!=", "eq", "ne", "in", "ni"], ["<", "<=", ">", ">="],
           ["+", "-"], ["*", "/", "%"]]  # fmt: skip
_BOOL = {"true": 1, "yes": 1, "on": 1, "false": 0, "no": 0, "off": 0}


def _number(value: str) -> int | float | None:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return None


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return f"{value:.1f}"
    return str(value)


def truth(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return value != 0
    low = str(value).strip().lower()
    if low in _BOOL:
        return bool(_BOOL[low])
    number = _number(low)
    if number is None:
        raise ScriptError(f"expected a boolean or number, got {value!r}")
    return number != 0


# --- interpreter -----------------------------------------------------------------------------


@dataclass
class Proc:
    params: list[str]
    body: str


@dataclass
class Frame:
    vars: dict[str, str]
    globals: set[str] = field(default_factory=set)


Call = Callable[[list[str]], Awaitable[str]]


class Sink(Protocol):
    """Where `puts` writes: a list, or a run's output file."""

    def append(self, text: str, /) -> None: ...


class Interp:
    """One evaluation over a session's variables and procedures."""

    def __init__(
        self,
        variables: dict[str, str],
        procs: dict[str, Proc],
        call: Call,
        is_command: Callable[[str], bool],
        source: Callable[[str], str],
        output: Sink,
        limits: Limits = LIMITS,
    ) -> None:
        self.top = Frame(variables)
        self.procs, self.call, self.is_command = procs, call, is_command
        self.source, self.output, self.limits = source, output, limits
        self.steps = 0
        self.depth = 0
        self.builtins: dict[str, Callable[[list[str], Frame], Awaitable[str]]] = {
            "set": self._set, "unset": self._unset, "incr": self._incr, "puts": self._puts,
            "if": self._if, "while": self._while, "foreach": self._foreach, "proc": self._proc,
            "return": self._return, "break": self._break, "continue": self._continue,
            "global": self._global, "catch": self._catch, "source": self._source,
            "expr": self._expr, "list": self._list, "llength": self._llength,
            "lindex": self._lindex, "lrange": self._lrange, "lappend": self._lappend,
            "join": self._join,
        }  # fmt: skip

    async def run(self, script: str) -> str:
        try:
            return await self._eval(script, self.top, top=True)
        except _Return as ret:
            return ret.value
        except (_Break, _Continue):
            raise ScriptError("break or continue outside a loop") from None

    # --- evaluation ----------------------------------------------------------------------------

    async def _eval(self, script: str, frame: Frame, *, top: bool = False) -> str:
        self.depth += 1
        try:
            if self.depth > self.limits.depth:
                raise ScriptError(f"too deeply nested (more than {self.limits.depth} levels)")
            result = ""
            for cmd in parse_script(script):
                try:
                    words = [await self._word(w, frame) for w in cmd.words]
                    result = await self._invoke(words, frame)
                except ScriptError as exc:
                    if top and exc.line is None:
                        exc.line = cmd.line
                    raise
            return result
        finally:
            self.depth -= 1

    async def _word(self, word: Word, frame: Frame) -> str:
        out = []
        for part in word.parts:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, Var):
                out.append(self._get(frame, part.name))
            else:
                out.append(await self._eval(part.script, frame))
        return self._sized("".join(out))

    async def _step(self) -> None:
        """Every command and every loop turn is a step (an empty loop body still counts)."""
        self.steps += 1
        if self.steps > self.limits.steps:
            raise ScriptError(f"stopped after {self.limits.steps} steps (the step limit)")
        if self.steps % 100 == 0:
            await asyncio.sleep(0)

    async def _invoke(self, words: list[str], frame: Frame) -> str:
        await self._step()
        name = words[0].removeprefix("/")
        if name in self.builtins:
            return await self.builtins[name](words[1:], frame)
        if name in self.procs:
            return await self._call_proc(self.procs[name], name, words[1:])
        if self.is_command(name):
            return self._sized(await self.call([name, *words[1:]]))
        raise ScriptError(f"unknown command {name!r}; `help` lists them")

    async def _call_proc(self, proc: Proc, name: str, args: list[str]) -> str:
        if len(args) != len(proc.params):
            raise ScriptError(f"{name} takes {len(proc.params)} argument(s), got {len(args)}")
        frame = Frame(dict(zip(proc.params, args, strict=True)))
        try:
            return await self._eval(proc.body, frame)
        except _Return as ret:
            return ret.value

    # --- variables -----------------------------------------------------------------------------

    def _scope(self, frame: Frame, name: str) -> dict[str, str]:
        return self.top.vars if name in frame.globals else frame.vars

    def _get(self, frame: Frame, name: str) -> str:
        scope = self._scope(frame, name)
        if name not in scope:
            raise ScriptError(f"no variable {name!r}")
        return scope[name]

    def _sized(self, value: str) -> str:
        if len(value) > self.limits.value_chars:
            raise ScriptError(f"a value is longer than {self.limits.value_chars} characters")
        return value

    def _items(self, value: str) -> list[str]:
        items = parse_list(value)
        if len(items) > self.limits.list_items:
            raise ScriptError(f"a list has more than {self.limits.list_items} items")
        return items

    @staticmethod
    def _arity(name: str, args: list[str], low: int, high: int | None = None) -> None:
        if len(args) < low or (high is not None and len(args) > high):
            raise ScriptError(f"wrong number of arguments to {name}")

    # --- built-ins -----------------------------------------------------------------------------

    async def _set(self, args: list[str], frame: Frame) -> str:
        self._arity("set", args, 1, 2)
        if len(args) == 1:
            return self._get(frame, args[0])
        self._scope(frame, args[0])[args[0]] = args[1]
        return args[1]

    async def _unset(self, args: list[str], frame: Frame) -> str:
        for name in args:
            self._scope(frame, name).pop(name, None)
        return ""

    async def _incr(self, args: list[str], frame: Frame) -> str:
        self._arity("incr", args, 1, 2)
        scope = self._scope(frame, args[0])
        current = _number(scope.get(args[0], "0"))
        step = _number(args[1]) if len(args) == 2 else 1
        if not isinstance(current, int) or not isinstance(step, int):
            raise ScriptError("incr works on integers")
        scope[args[0]] = str(current + step)
        return scope[args[0]]

    async def _puts(self, args: list[str], frame: Frame) -> str:
        self._arity("puts", args, 1, 1)
        self.output.append(args[0])
        return ""

    async def _if(self, args: list[str], frame: Frame) -> str:
        i = 0
        while i < len(args):
            cond = args[i]
            i += 1
            if i < len(args) and args[i] == "then":
                i += 1
            if i >= len(args):
                raise ScriptError("if: missing body")
            if truth(await self._evaluate(cond, frame)):
                return await self._eval(args[i], frame)
            i += 1
            if i >= len(args):
                return ""
            if args[i] == "elseif":
                i += 1
                continue
            if args[i] == "else" and i + 1 == len(args) - 1:
                return await self._eval(args[i + 1], frame)
            if i == len(args) - 1:
                return await self._eval(args[i], frame)  # Tcl's bare else body
            raise ScriptError("if: expected elseif or else")
        raise ScriptError("if: missing condition")

    async def _while(self, args: list[str], frame: Frame) -> str:
        self._arity("while", args, 2, 2)
        while truth(await self._evaluate(args[0], frame)):
            await self._step()
            try:
                await self._eval(args[1], frame)
            except _Break:
                break
            except _Continue:
                continue
        return ""

    async def _foreach(self, args: list[str], frame: Frame) -> str:
        self._arity("foreach", args, 3, 3)
        names, items = self._items(args[0]), self._items(args[1])
        if not names:
            raise ScriptError("foreach: name a variable")
        for start in range(0, len(items), len(names)):
            await self._step()
            for k, name in enumerate(names):
                at = start + k
                self._scope(frame, name)[name] = items[at] if at < len(items) else ""
            try:
                await self._eval(args[2], frame)
            except _Break:
                break
            except _Continue:
                continue
        return ""  # loop variables stay set, as in Tcl

    async def _proc(self, args: list[str], frame: Frame) -> str:
        self._arity("proc", args, 3, 3)
        name = args[0]
        if name in self.builtins or self.is_command(name):
            raise ScriptError(f"{name!r} is a built-in or CTFlow command; choose another name")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name):
            raise ScriptError("procedure names use letters, digits, - and _")
        if name not in self.procs and len(self.procs) >= self.limits.procs:
            raise ScriptError(f"at most {self.limits.procs} procedures")
        self.procs[name] = Proc(self._items(args[1]), args[2])
        return ""

    async def _return(self, args: list[str], frame: Frame) -> str:
        self._arity("return", args, 0, 1)
        raise _Return(args[0] if args else "")

    async def _break(self, args: list[str], frame: Frame) -> str:
        raise _Break

    async def _continue(self, args: list[str], frame: Frame) -> str:
        raise _Continue

    async def _global(self, args: list[str], frame: Frame) -> str:
        frame.globals.update(args)
        return ""

    async def _catch(self, args: list[str], frame: Frame) -> str:
        self._arity("catch", args, 1, 2)
        try:
            value, code = await self._eval(args[0], frame), "0"
        except ScriptError as exc:
            value, code = exc.message, "1"
        except Problem as exc:
            value, code = exc.detail or str(exc), "1"
        if len(args) == 2:
            self._scope(frame, args[1])[args[1]] = value
        return code

    async def _source(self, args: list[str], frame: Frame) -> str:
        self._arity("source", args, 1, 1)
        return await self._eval(self.source(args[0]), frame)

    async def _expr(self, args: list[str], frame: Frame) -> str:
        return _text(await self._evaluate(" ".join(args), frame))

    async def _list(self, args: list[str], frame: Frame) -> str:
        return format_list(args)

    async def _llength(self, args: list[str], frame: Frame) -> str:
        self._arity("llength", args, 1, 1)
        return str(len(self._items(args[0])))

    async def _lindex(self, args: list[str], frame: Frame) -> str:
        self._arity("lindex", args, 2, 2)
        items = self._items(args[0])
        at = self._index(args[1], len(items))
        return items[at] if 0 <= at < len(items) else ""

    async def _lrange(self, args: list[str], frame: Frame) -> str:
        self._arity("lrange", args, 3, 3)
        items = self._items(args[0])
        first, last = self._index(args[1], len(items)), self._index(args[2], len(items))
        return format_list(items[max(first, 0) : last + 1])

    async def _lappend(self, args: list[str], frame: Frame) -> str:
        self._arity("lappend", args, 1)
        scope = self._scope(frame, args[0])
        items = [*self._items(scope.get(args[0], "")), *args[1:]]
        if len(items) > self.limits.list_items:
            raise ScriptError(f"a list has more than {self.limits.list_items} items")
        scope[args[0]] = self._sized(format_list(items))
        return scope[args[0]]

    async def _join(self, args: list[str], frame: Frame) -> str:
        self._arity("join", args, 1, 2)
        return self._sized((args[1] if len(args) == 2 else " ").join(self._items(args[0])))

    @staticmethod
    def _index(raw: str, length: int) -> int:
        if raw == "end":
            return length - 1
        if raw.startswith("end-") and raw[4:].isdigit():
            return length - 1 - int(raw[4:])
        number = _number(raw)
        if not isinstance(number, int):
            raise ScriptError(f"bad index {raw!r}")
        return number

    # --- expr ----------------------------------------------------------------------------------

    async def _evaluate(self, text: str, frame: Frame) -> Any:
        tokens = self._tokens(text)
        value, rest = await self._binary(tokens, 0, frame)
        if rest:
            raise ScriptError(f"syntax error in expression {text!r}")
        return value

    def _tokens(self, text: str) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        i, n = 0, len(text)
        while i < n:
            if text[i].isspace():
                i += 1
            elif text[i] == "$" or text[i] == "[":
                parts, i = _subst_parts(text, i, lambda ch: ch.isspace() or ch in "()<>=!&|+-*/%")
                out.append(("parts", parts))
            elif text[i] == '"':
                parts, i = _subst_parts(text, i + 1, lambda ch: ch == '"')
                out.append(("parts", parts))
                i += 1
            elif text[i] == "{":
                end = _matching(text, i)
                out.append(("str", text[i + 1 : end - 1]))
                i = end
            else:
                m = _TOKEN.match(text, i)
                if m is None or m.end() == i:
                    raise ScriptError(f"syntax error in expression {text!r}")
                if m.group("num") is not None:
                    out.append(("num", _number(m.group("num"))))
                elif m.group("op") is not None:
                    out.append(("op", m.group("op")))
                else:
                    word = m.group("word")
                    if word in {"eq", "ne", "in", "ni"}:
                        out.append(("op", word))
                    elif word.lower() in _BOOL:
                        out.append(("num", _BOOL[word.lower()]))
                    else:
                        raise ScriptError(f"quote the string {word!r} in the expression")
                i = m.end()
        return out

    async def _binary(
        self, tokens: list[tuple[str, Any]], level: int, frame: Frame
    ) -> tuple[Any, list[tuple[str, Any]]]:
        if level == len(_BINARY):
            return await self._unary(tokens, frame)
        left, rest = await self._binary(tokens, level + 1, frame)
        while rest and rest[0][0] == "op" and rest[0][1] in _BINARY[level]:
            op = rest[0][1]
            if op in {"&&", "||"} and truth(left) == (op == "||"):
                # short-circuit: the right side is parsed, not evaluated
                rest = self._skip(rest[1:])
                left = 1 if op == "||" else 0
                continue
            right, rest = await self._binary(rest[1:], level + 1, frame)
            left = _apply(op, left, right, self._items)
        return left, rest

    @staticmethod
    def _skip(tokens: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
        depth, i = 0, 0
        while i < len(tokens):
            kind, value = tokens[i]
            if kind == "op" and value == "(":
                depth += 1
            elif kind == "op" and value == ")":
                if depth == 0:
                    break
                depth -= 1
            elif kind == "op" and depth == 0 and value in {"&&", "||"}:
                break
            i += 1
        return tokens[i:]

    async def _unary(
        self, tokens: list[tuple[str, Any]], frame: Frame
    ) -> tuple[Any, list[tuple[str, Any]]]:
        if not tokens:
            raise ScriptError("incomplete expression")
        kind, value = tokens[0]
        if kind == "op" and value in {"!", "-", "+"}:
            operand, rest = await self._unary(tokens[1:], frame)
            if value == "!":
                return int(not truth(operand)), rest
            number = _number(str(operand)) if not isinstance(operand, (int, float)) else operand
            if number is None:
                raise ScriptError(f"expected a number, got {operand!r}")
            return (-number if value == "-" else number), rest
        if kind == "op" and value == "(":
            inner, rest = await self._binary(tokens[1:], 0, frame)
            if not rest or rest[0] != ("op", ")"):
                raise ScriptError("missing ) in expression")
            return inner, rest[1:]
        if kind == "num" or kind == "str":
            return value, tokens[1:]
        if kind == "parts":
            text = await self._word(Word(value), frame)
            number = _number(text.strip())
            return (text if number is None else number), tokens[1:]
        raise ScriptError(f"unexpected {value!r} in expression")


def _apply(op: str, left: Any, right: Any, items: Callable[[str], list[str]]) -> Any:
    if op in {"eq", "ne"}:
        return int((_text(left) == _text(right)) == (op == "eq"))
    if op in {"in", "ni"}:
        return int((_text(left) in items(_text(right))) == (op == "in"))
    if op in {"&&", "||"}:
        return int(truth(right))
    numbers = [v if isinstance(v, (int, float)) else _number(str(v)) for v in (left, right)]
    if op in {"==", "!=", "<", "<=", ">", ">="}:
        pair: list[Any] = numbers if None not in numbers else [_text(left), _text(right)]
        a, b = pair
        result = {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}
        return int(result[op])
    x, y = numbers
    if x is None or y is None:
        raise ScriptError(f"expected numbers for {op}, got {left!r} and {right!r}")
    if op in {"/", "%"} and y == 0:
        raise ScriptError("divide by zero")
    if op == "/" and isinstance(x, int) and isinstance(y, int):
        return x // y
    return {"+": x + y, "-": x - y, "*": x * y, "/": x / y, "%": x % y}[op]
