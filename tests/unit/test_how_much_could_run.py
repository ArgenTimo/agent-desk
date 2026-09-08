"""How much work could be started right now, and why that is the number
(01M1X8DA7M7N0WQ9MKK8B9521B).

"Сколько работы можно вести параллельно — это функция от того, на сколько независимых кусков
разбивается задача, и от правил, которые уже есть: один агент на проект, бюджет в час, два падения
подряд выключают. Число должно вычисляться и объясняться, а не задаваться."

Every rule was already there and none of them was ever added up. Each project knew, one at a time,
why it could not start anything; nobody could see the answer to "how much could be going on here",
which is the question somebody asks before queueing five more things.
"""

from __future__ import annotations

import ast
import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import room
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
BOARD = HERE / "agent_desk" / "web" / "templates" / "board.html"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _seat(name: str, *, free: bool = True, why: str = "", waiting: int = 1) -> room.Seat:
    return room.Seat(repo_key=f"origin:{name}", name=name, free=free, why=why, waiting=waiting)


# --- the number -----------------------------------------------------------------------------------
def test_it_is_one_per_free_project() -> None:
    """One agent per project is the rule this adds up; it does not invent a second one."""
    found = room.how_many([_seat("api"), _seat("web"), _seat("docs", free=False, why="not armed")])

    assert found.at_once == 2


def test_a_desk_with_nothing_in_it_says_so_rather_than_zero() -> None:
    """ "0 could start now" over an empty board reads as a rule stopping something."""
    assert room.how_many([]).said == "nothing here to start work in"


def test_a_desk_where_nothing_can_start_says_that() -> None:
    assert room.how_many([_seat("api", free=False, why="not armed")]).said == (
        "nothing could start right now"
    )


def test_the_number_says_what_it_is_out_of() -> None:
    said = room.how_many([_seat("api"), _seat("web", free=False, why="not armed")]).said

    assert said == "1 could start now, of 2"


# --- and the reason for every one of them -----------------------------------------------------------
def test_a_project_that_cannot_start_says_why() -> None:
    """The reason is the whole point: "three" is a number to argue with, "three, and this one is
    disarmed after two failures" is something to act on."""
    (line,) = room.how_many([_seat("api", free=False, why="one is already running")]).lines

    assert line == "api could not: one is already running"


def test_a_project_that_can_says_how_much_is_waiting() -> None:
    (line,) = room.how_many([_seat("api", waiting=3)]).lines

    assert line == "api could start one now — 3 things queued"


def test_one_thing_queued_is_not_called_things() -> None:
    (line,) = room.how_many([_seat("api", waiting=1)]).lines

    assert "1 thing queued" in line


def test_every_project_gets_a_line_free_or_not() -> None:
    """A list that showed only the blocked ones would answer a different question."""
    found = room.how_many([_seat("api"), _seat("web", free=False, why="nothing is queued")])

    assert len(found.lines) == 2


def test_the_reasons_are_not_recomputed_here() -> None:
    """A function that worked the rules out again would be a second copy of `autostart.why_not`
    disagreeing with it on a Tuesday — and the loop's own decision is the one worth showing."""
    # Against the code and not the prose. The module explains the rules it is deliberately not
    # applying, and a substring check over the file trips on its own documentation.
    tree = ast.parse((HERE / "agent_desk" / "room.py").read_text(encoding="utf-8"))
    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for rule in ("per_hour", "AT_ONCE", "armed", "FAILURES_BEFORE_DISARM", "why_not"):
        assert rule not in named, rule


# --- the route ------------------------------------------------------------------------------------
async def test_the_route_answers_with_the_number_and_the_reasons(desk: Store) -> None:
    answer = await routes.how_much_could_run()
    said = json.loads(bytes(answer.body).decode())

    assert set(said) == {"at_once", "said", "lines"}
    assert isinstance(said["at_once"], int)


async def test_the_route_asks_the_function_the_loop_asks(desk: Store) -> None:
    source = (HERE / "agent_desk" / "web" / "routes.py").read_text(encoding="utf-8")
    start = source.index("async def how_much_could_run(")
    body = source[start : source.index("\n\n\n", start)]

    assert "autostart.why_not(" in body


# --- and it is on the page ----------------------------------------------------------------------------
def test_the_console_shows_it_and_the_reasons_together() -> None:
    markup = BOARD.read_text(encoding="utf-8")
    source = CONSOLE.read_text(encoding="utf-8")

    assert 'id="room"' in markup
    assert "room-lines" in markup
    assert "fetch('/room')" in source


def test_a_count_that_could_not_be_read_is_left_alone() -> None:
    """Replaced with a zero it would read as "nothing can run", which is a claim."""
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("async function readRoom(")
    body = source[start : source.index("\n}\n", start)]

    assert "catch {" in body
    assert "= 0" not in body


def test_it_is_read_on_the_same_beat_as_the_board() -> None:
    """Every input to it — a seat taken, a budget spent, a project disarmed — is something the
    board push is already about."""
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("stream.addEventListener('board'")
    handler = source[start : source.index("\n});\n", start)]

    assert "readRoom()" in handler
