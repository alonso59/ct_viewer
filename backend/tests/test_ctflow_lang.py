"""CTF-07: the CTFlow language — Tcl-like semantics, limits, and no way out but registered
commands (no files, processes, environment or network)."""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import ValidationProblem
from app.ctflow.lang import Interp, Limits, Proc, ScriptError, format_list, parse_list

DOMAIN = {"segment", "cases"}


def run(
    script: str,
    variables: dict[str, str] | None = None,
    procs: dict[str, Proc] | None = None,
    limits: Limits | None = None,
    library: dict[str, str] | None = None,
) -> tuple[str, list[str], list[list[str]]]:
    """(result, puts output, domain calls)."""
    calls: list[list[str]] = []
    output: list[str] = []

    async def call(words: list[str]) -> str:
        calls.append(words)
        if words[0] == "cases":
            return "case_1 case_2 {case 3}"
        if words[1:] == ["refused"]:
            raise ValidationProblem("not ready")
        return f"run-{len(calls)}"

    def source(name: str) -> str:
        if library is None or name not in library:
            raise ScriptError(f"no script {name!r}")
        return library[name]

    interp = Interp(
        {} if variables is None else variables,
        {} if procs is None else procs,
        call, DOMAIN.__contains__, source, output, limits or Limits(),
    )  # fmt: skip
    return asyncio.run(interp.run(script)), output, calls


def test_variables_substitution_and_quoting() -> None:
    value, out, _ = run('set a 2; set b "x $a"; puts $b; puts {no $a here}; puts [set a]')
    assert out == ["x 2", "no $a here", "2"] and value == ""
    assert run("set n 3\nexpr {$n * (2 + 1) - 1}")[0] == "8"
    assert run(r'puts "tab\tend"')[1] == ["tab\tend"]
    assert run("# a comment\nset x 1 ;# trailing\n")[0] == "1"


def test_control_flow() -> None:
    script = """
    set total 0
    foreach i {1 2 3 4 5} {
        if {$i == 2} { continue } elseif {$i > 4} { break } else { incr total $i }
    }
    set n 0
    while {$n < 3} { incr n }
    expr {$total + $n}
    """
    assert run(script)[0] == "11"  # 1 + 3 + 4, then 3
    assert run("foreach {a b} {1 2 3 4} { set last $a$b }; set last")[0] == "34"
    assert run('if {"x" eq "x" && 2 in {1 2}} { set r yes } else { set r no }')[0] == "yes"
    assert run("expr {1 || [undefined]}")[0] == "1"  # short-circuit: never evaluated


def test_procedures_returns_and_scopes() -> None:
    variables: dict[str, str] = {}
    procs: dict[str, Proc] = {}
    run("proc double {x} { return [expr {$x * 2}] }; set g 5", variables, procs)
    assert run("double 21", variables, procs)[0] == "42"  # defined in an earlier line
    assert run("proc peek {} { global g; return $g }; peek", variables, procs)[0] == "5"
    with pytest.raises(ScriptError, match="no variable 'g'"):
        run("proc blind {} { return $g }; blind", variables, procs)
    with pytest.raises(ScriptError, match="built-in or CTFlow command"):
        run("proc segment {} {}")


def test_lists() -> None:
    assert run("llength [list a {b c} d]")[0] == "3"
    assert run("lindex {a {b c} d} 1")[0] == "b c"
    assert run("lindex {a b c} end")[0] == "c"
    assert run("lrange {a b c d} 1 end-1")[0] == "b c"
    assert run("set l {}; lappend l x {y z}; llength $l")[0] == "2"
    assert run("join {a b c} ,")[0] == "a,b,c"


@given(st.lists(st.text(alphabet=' ab{}[]"$\\;\n', max_size=6), max_size=6))
def test_lists_round_trip(items: list[str]) -> None:
    assert parse_list(format_list(items)) == items


def test_domain_commands_get_evaluated_words_and_return_values() -> None:
    script = """
    set done {}
    foreach c [cases] {
        if {[catch {segment $c -gpus 2} err]} { puts "skip $c: $err" } else { lappend done $c }
    }
    llength $done
    """
    value, out, calls = run(script)
    assert value == "3" and out == []
    assert calls[1:] == [["segment", c, "-gpus", "2"] for c in ("case_1", "case_2", "case 3")]
    value, out, _ = run("catch {segment refused} msg; set msg")
    assert value == "not ready"


def test_errors_name_their_line() -> None:
    with pytest.raises(ScriptError) as exc:
        run("set a 1\nset b 2\nnope x")
    assert exc.value.line == 3 and "unknown command 'nope'" in exc.value.message
    with pytest.raises(ScriptError, match="missing close-brace"):
        run("puts {open")
    with pytest.raises(ScriptError, match="divide by zero"):
        run("expr {1 / 0}")


@pytest.mark.parametrize(
    "script",
    [
        "exec ls /",
        "open /etc/passwd",
        "file delete /tmp/x",
        "socket example.org 80",
        "eval {puts hi}",
        "uplevel 1 {set x 1}",
        "interp create",
        "load libc.so",
        "env HOME",
        "subst {$x}",
        "set x {[exec ls]}; puts $x",  # braces stay literal: the text is never run
    ],
)
def test_nothing_reaches_the_operating_system(script: str) -> None:
    """No built-in opens files, starts processes, reads the environment or the network."""
    try:
        _, out, calls = run(script)
    except ScriptError as exc:
        assert "unknown command" in exc.message
    else:
        assert calls == [] and out in ([], ["[exec ls]"])


def test_source_reads_only_through_the_library() -> None:
    lib = {"helpers.ctf": "proc triple {x} { expr {$x * 3} }"}
    assert run("source helpers.ctf; triple 4", library=lib)[0] == "12"
    with pytest.raises(ScriptError, match="no script"):
        run("source /etc/passwd", library=lib)


def test_limits_stop_runaway_scripts() -> None:
    small = Limits(steps=500, depth=10, value_chars=1000, list_items=50, procs=2)
    with pytest.raises(ScriptError, match="step limit"):
        run("while 1 {}", limits=small)
    with pytest.raises(ScriptError, match="too deeply nested"):
        run("proc r {} { r }; r", limits=small)
    with pytest.raises(ScriptError, match="longer than 1000"):
        run("set s x; while 1 { set s $s$s }", limits=small)
    with pytest.raises(ScriptError, match="more than 50 items"):
        run("set l {}; while 1 { lappend l x }", limits=small)
    with pytest.raises(ScriptError, match="at most 2 procedures"):
        run("proc a {} {}; proc b {} {}; proc c {} {}", limits=small)


def test_a_long_loop_yields_to_other_work() -> None:
    async def both() -> int:
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0)

        task = asyncio.create_task(ticker())
        noop = Interp({}, {}, lambda w: asyncio.sleep(0, ""), lambda n: False, str, [])
        with pytest.raises(ScriptError):
            await noop.run("while 1 {}")
        task.cancel()
        return ticks

    assert asyncio.run(both()) > 10
