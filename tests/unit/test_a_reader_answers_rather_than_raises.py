"""Every function in this program that is handed something, over what nothing here would hand it.

Two families, and the same question of both: is there an input at all that makes this raise
instead of answer, and does asking twice give the same answer.

**The readers**: a model's reply, a URL somebody typed into a field, a blob a row has held
since before the shape it is in existed. Not one of them is handed its input by this program's own
code — a model's next answer is not a value anybody chose, and a field is whatever was typed into
it — so the interesting question about each is not what it does with a good input but whether there
is an input at all that makes it raise instead of answer.

Asserted by sweeping rather than by listing, for the reason `tests/unit/test_the_store_itself.py`
sweeps: a list is a thing somebody has to remember to add to, and the reader added next week is
exactly the one nobody would.

**The arrangers** take a sequence of this program's own shapes — cards, steps, rows — and answer
with an order, a drawing or a sentence. Their inputs are built here rather than typed in, so what
is hostile about them is not the characters but the shape: nothing on the bench at all, the same
card twice, five hundred of them.

What neither can check is the *value* — whether `read_shape` read the shape correctly is what the
tests beside it are for. What they check is that there is an answer at all, and that asking twice
gives the same one.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import itertools
import typing
from types import FunctionType, ModuleType

import pytest

pytestmark = pytest.mark.unit

# The modules whose readers this sweeps. Named rather than discovered, because `agent_desk.web`
# and `agent_desk.store` take a store or a request and are not this kind of thing at all.
MODULES = (
    "allowed",
    "because",
    "boxed",
    "branching",
    "carrying",
    "checking",
    "combining",
    "comparing",
    "connectors",
    "describing",
    "diagrams",
    "engines",
    "finding",
    "grading",
    "handling",
    "looking",
    "narrowing",
    "opening",
    "pasted",
    "process",
    "recalling",
    "repeating",
    "roles",
    "room",
    "seen",
    "showing",
    "slots",
    "spread",
    "standing",
    "starting",
    "telling",
    "ties",
    "tidying",
    "tooling",
)

# The one that is excluded, and why. `open_it` starts a process: sweeping it would open a terminal
# window on the machine running the suite, once per input. Its own file covers the same property —
# including the null byte a path parameter can carry into it, which is what put it on this list.
NOT_A_READER = {"opening.open_it"}

# What a reader is handed by a model, a form field or a row that is older than the shape it is in.
HOSTILE_TEXT = (
    "",
    "   ",
    "\n\n\t",
    "\x00",
    "a\x00b",
    "x" * 20_000,
    "🙂🙂🙂",
    "«ъ»",
    "null",
    "{}",
    "[]",
    '{"handling": {"marked": "not a list"}}',
    "0",
    "-",
    "..",
    "../../etc/passwd",
    "-rf",
    "--flag",
    "%00%2e%2e",
    "<script>alert(1)</script>",
    "\r\n\r\n",
    "line\nline\nline",
)
HOSTILE_NUMBER = (0, -1, 1, 2**31, -(2**31))
HOSTILE = {str: HOSTILE_TEXT, int: HOSTILE_NUMBER, bool: (True, False)}


def _readers() -> list[tuple[str, FunctionType]]:
    """Every public function in those modules whose arguments are all text, numbers or flags.

    The type hints are the source: a function that takes a `Card` is handed one by this program's
    own code and its arguments are the type checker's business, while a function that takes a `str`
    is handed whatever arrived.
    """
    found: list[tuple[str, FunctionType]] = []
    for name in MODULES:
        module: ModuleType = importlib.import_module(f"agent_desk.{name}")
        for what, function in inspect.getmembers(module, inspect.isfunction):
            if what.startswith("_") or function.__module__ != module.__name__:
                continue
            if inspect.iscoroutinefunction(function) or f"{name}.{what}" in NOT_A_READER:
                continue
            hints = typing.get_type_hints(function)
            wanted = [
                one
                for one in inspect.signature(function).parameters.values()
                if one.default is inspect.Parameter.empty
                and one.kind not in (one.VAR_POSITIONAL, one.VAR_KEYWORD)
            ]
            if wanted and all(hints.get(one.name) in HOSTILE for one in wanted):
                found.append((f"{name}.{what}", function))
    return sorted(found)


READERS = _readers()


def test_the_sweep_finds_the_readers_it_is_about() -> None:
    """A sweep that silently found nothing would pass for ever. These are named because they are
    the ones whose input has been wrong in this repository before."""
    names = {name for name, _ in READERS}

    assert len(READERS) >= 40
    assert {
        "handling.read_json",
        "telling.read_shape",
        "starting.key_and_name",
        "connectors.guess",
        "seen.read",
        "tidying.may_close",
    } <= names


@pytest.mark.parametrize(("name", "reader"), READERS, ids=[name for name, _ in READERS])
def test_a_reader_answers_rather_than_raises(name: str, reader: FunctionType) -> None:
    hints = typing.get_type_hints(reader)
    wanted = [
        one
        for one in inspect.signature(reader).parameters.values()
        if one.default is inspect.Parameter.empty
        and one.kind not in (one.VAR_POSITIONAL, one.VAR_KEYWORD)
    ]
    # Bounded, because a reader of four strings would otherwise be a quarter of a million calls.
    space = itertools.islice(itertools.product(*[HOSTILE[hints[one.name]] for one in wanted]), 400)

    for combination in space:
        given = dict(zip([one.name for one in wanted], combination, strict=True))

        once = reader(**given)
        twice = reader(**given)

        assert once == twice, f"{name} answered differently the second time for {given!r}"


# --- and the other family: the ones handed an arrangement ------------------------------------------
# These take a sequence of cards, steps or rows and answer with an order, a drawing or a sentence.
# Their inputs are built by this program rather than typed into it, so what is hostile about them is
# not the characters but the shape: nothing on the bench, the same card twice, five hundred of them.
ARRANGEMENTS = (
    ("empty", 0),
    ("one", 1),
    ("the same thing twice", 2),
    ("five hundred", 500),
)


def _one_of(kind: type, name: str = "a") -> object | None:
    """One instance of a dataclass, every required field filled from its own type."""
    if not dataclasses.is_dataclass(kind):
        return None
    hints = typing.get_type_hints(kind)
    made: dict[str, object] = {}
    for field in dataclasses.fields(kind):
        if field.default is not dataclasses.MISSING:
            continue
        if field.default_factory is not dataclasses.MISSING:
            continue
        hint = hints.get(field.name)
        origin = typing.get_origin(hint)
        if hint is str:
            # The fields that name a card are what the lines between cards are matched on, so they
            # get the name and everything else gets something that is not one.
            made[field.name] = name if field.name in ("name", "from_name", "to_name", "id") else "x"
        elif hint is int:
            made[field.name] = 1
        elif hint is bool:
            made[field.name] = False
        elif hint is float:
            made[field.name] = 1.0
        elif origin in (list, tuple, set, frozenset):
            made[field.name] = origin()
        elif origin is dict:
            made[field.name] = {}
        elif isinstance(hint, type) and dataclasses.is_dataclass(hint):
            inner = _one_of(hint, name)
            if inner is None:
                return None
            made[field.name] = inner
        else:
            return None
    return kind(**made)


def _arrangers() -> list[tuple[str, FunctionType, list[tuple[str, type | None]]]]:
    """Every public function whose arguments are sequences of one of this program's own shapes."""
    found = []
    for name in MODULES:
        module: ModuleType = importlib.import_module(f"agent_desk.{name}")
        for what, function in inspect.getmembers(module, inspect.isfunction):
            if what.startswith("_") or function.__module__ != module.__name__:
                continue
            if inspect.iscoroutinefunction(function):
                continue
            hints = typing.get_type_hints(function)
            wanted = [
                one
                for one in inspect.signature(function).parameters.values()
                if one.default is inspect.Parameter.empty
                and one.kind not in (one.VAR_POSITIONAL, one.VAR_KEYWORD)
            ]
            plan: list[tuple[str, type | None]] = []
            readable = True
            for one in wanted:
                hint = hints.get(one.name)
                inside = typing.get_args(hint)
                if hint in (str, int, bool):
                    plan.append((hint.__name__, None))
                elif (
                    inside
                    and typing.get_origin(hint)
                    and isinstance(inside[0], type)
                    and dataclasses.is_dataclass(inside[0])
                ):
                    plan.append(("many", inside[0]))
                else:
                    readable = False
                    break
            if readable and plan and any(kind == "many" for kind, _ in plan):
                found.append((f"{name}.{what}", function, plan))
    return sorted(found, key=lambda one: one[0])


ARRANGERS = _arrangers()


def test_the_sweep_finds_the_arrangers_it_is_about() -> None:
    names = {name for name, _, _ in ARRANGERS}

    assert len(ARRANGERS) >= 12
    assert {"process.order", "telling.as_words", "diagrams.as_mermaid", "carrying.as_document"} <= (
        names
    )


@pytest.mark.parametrize(
    ("name", "arranger", "plan"), ARRANGERS, ids=[name for name, _, _ in ARRANGERS]
)
@pytest.mark.parametrize(("shape", "how_many"), ARRANGEMENTS, ids=[one for one, _ in ARRANGEMENTS])
def test_an_arranger_answers_rather_than_raises(
    name: str,
    arranger: FunctionType,
    plan: list[tuple[str, type | None]],
    shape: str,
    how_many: int,
) -> None:
    """Nothing on the bench is the ordinary case on a console somebody has just opened; the same
    card twice is what a line drawn between a card and itself looks like from in here; and five
    hundred is the number the workbench was measured at when it stopped being readable."""
    wanted = [
        one
        for one in inspect.signature(arranger).parameters.values()
        if one.default is inspect.Parameter.empty
        and one.kind not in (one.VAR_POSITIONAL, one.VAR_KEYWORD)
    ]
    given: dict[str, object] = {}
    for one, (kind, of) in zip(wanted, plan, strict=True):
        if kind == "str":
            given[one.name] = "a"
        elif kind == "int":
            given[one.name] = 1
        elif kind == "bool":
            given[one.name] = False
        else:
            assert of is not None
            made = _one_of(of)
            assert made is not None, f"{name} takes a {of.__name__} this cannot build"
            given[one.name] = (
                [made] * how_many
                if how_many < 500
                else [_one_of(of, f"n{n}") or made for n in range(500)]
            )

    once = arranger(**given)
    twice = arranger(**given)

    assert once == twice, f"{name} answered differently the second time for {shape}"
