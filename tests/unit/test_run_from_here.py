"""Start the branch you are thinking about, not everything (01M1XA1V87G6MGV6AQ7M4YMRFW).

"Карточка с кнопкой пуск — нажимая на неё, система берёт данные из карточки ввода и направляет их
далее… Отдельная карточка, а не кнопка на панели: в схеме может быть несколько независимых веток, и
запускать хочется ту, над которой сейчас думаешь, а не всё сразу."

The complaint is about the *panel*: one button that runs everything cannot start one branch. So the
control is on the card it starts from, which is what the sentence asks for and needs no sixth role
to say — a card that runs a branch is the step at the head of it.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk import process
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _cards(*names: str) -> list[process.Card]:
    return [
        process.Card(name=name, role="action", label=name, said={"asks": f"do {name}"})
        for name in names
    ]


def _line(one: str, other: str) -> process.Line:
    return process.Line(from_name=one, to_name=other, kind="then")


# --- which cards a branch is ------------------------------------------------------------------------
def test_a_branch_is_the_card_and_everything_after_it() -> None:
    cards = _cards("a", "b", "c", "d")
    lines = [_line("a", "b"), _line("c", "d")]

    assert process.from_here("a", cards, lines) == ("a", "b")
    assert process.from_here("c", cards, lines) == ("c", "d")


def test_what_feeds_it_is_not_re_run() -> None:
    """Its result is already on the card, and re-doing it to reach the part somebody pressed is
    exactly what "не всё сразу" is asking not to happen."""
    cards = _cards("first", "second")

    assert process.from_here("second", cards, [_line("first", "second")]) == ("second",)


def test_a_lone_card_is_a_branch_of_one() -> None:
    assert process.from_here("a", _cards("a"), []) == ("a",)


def test_a_card_that_is_not_here_is_no_branch() -> None:
    assert process.from_here("gone", _cards("a"), []) == ()


def test_a_branch_runs_in_the_order_the_whole_drawing_would() -> None:
    """So running part of a drawing does the same thing to that part as running all of it."""
    cards = _cards("a", "b", "c")
    lines = [_line("a", "b"), _line("b", "c")]

    assert process.from_here("a", cards, lines) == ("a", "b", "c")


def test_two_ways_into_one_card_do_not_list_it_twice() -> None:
    cards = _cards("a", "b", "join")
    lines = [_line("a", "b"), _line("a", "join"), _line("b", "join")]

    assert process.from_here("a", cards, lines) == ("a", "b", "join")


def test_a_loop_does_not_hang() -> None:
    """Somebody can draw both lines, and a control that hangs on it is worse than one that says no.

    It comes back empty rather than in some order, because `order` refuses to order a tangle and
    this asks it — which is the same answer `ready_to_run` already gives such a drawing, in the
    same words. Two cards in a loop is not a branch with a beginning.
    """
    cards = _cards("a", "b")
    lines = [_line("a", "b"), _line("b", "a")]

    assert process.from_here("a", cards, lines) == ()
    assert process.order(cards, lines).tangled


# --- the route ---------------------------------------------------------------------------------------
async def _press(desk: Store, cards: str, start: str) -> tuple[int, dict[str, object]]:
    class Request:
        async def body(self) -> bytes:
            from urllib.parse import urlencode

            return urlencode({"cards": cards, "from": start}).encode()

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    answer = await routes.start_run(Request())  # type: ignore[arg-type]
    return answer.status_code, json.loads(bytes(answer.body).decode())


async def test_pressing_a_card_runs_its_branch_only(desk: Store) -> None:
    made = {}
    for name in ("a", "b", "c"):
        card = await desk.add_step_card(name)
        await desk.set_card_role(card.name, "action")
        await desk.set_card_field(card.name, "asks", f"do {name}")
        made[name] = card.name
    await desk.tie_cards(from_name=made["a"], to_name=made["b"], kind="then", says="")

    status, said = await _press(desk, ",".join(made.values()), made["a"])

    assert status == 200, said
    (run,) = await desk.runs()
    assert run.cards == f"{made['a']},{made['b']}"


async def test_pressing_a_card_that_is_not_on_the_bench_starts_nothing(desk: Store) -> None:
    status, said = await _press(desk, "", "step:gone")

    assert status == 409
    assert "not on the workbench" in str(said["why"])
    assert await desk.runs() == []


# --- and the control ----------------------------------------------------------------------------------
def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def test_the_control_is_on_the_card_and_not_on_the_panel() -> None:
    source = _code()

    assert 'class="pin-run"' in source
    assert "runFromHere(event.target.closest('.pin'))" in source


def test_it_is_offered_only_on_a_card_that_runs() -> None:
    """An Object does not do anything, so a run starting at one would begin by doing nothing."""
    source = _code()
    start = source.index("function showRunFrom(")
    body = source[start : source.index("\n}\n", start)]

    assert "role === 'action' || role === 'decision' || role === 'event'" in body


def test_the_branch_is_worked_out_on_the_server() -> None:
    """The order a branch runs in is `process.order`'s answer, and a second one on the page would
    be a second answer."""
    source = _code()
    start = source.index("async function runFromHere(")
    body = source[start : source.index("\n}\n", start)]

    assert "from: name" in body
    assert "order" not in body
