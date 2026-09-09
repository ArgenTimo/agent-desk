"""The console notices that you keep doing the same thing (01M1XED1DYFK1QRTHZDHHGY8W9).

«Три раза подряд: собрал те же три карточки, задал тот же по форме вопрос, запустил. Консоль
предлагает сохранить это как процесс — уже собранный, с полями, заполненными по тому, что делалось.»
"""

from __future__ import annotations

import json
import pathlib
import urllib.parse
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk import repeating
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _a_form(fields: dict[str, str]) -> object:
    body = urllib.parse.urlencode(fields).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()


CONTEXT = "idea · a thought\nsession · biba (1 session)"


# --- what "the same" means -----------------------------------------------------------------------
def test_the_same_shape_is_the_same_kinds_and_the_same_opening_words() -> None:
    """Not the same cards — the whole point is that the third time was about a different idea."""
    one = repeating.shape_of("Draft a plan for the migration", CONTEXT)
    two = repeating.shape_of("Draft a plan for the reader", CONTEXT)

    assert one == two


def test_a_different_question_is_a_different_shape() -> None:
    one = repeating.shape_of("Draft a plan for the migration", CONTEXT)
    two = repeating.shape_of("What is it doing right now", CONTEXT)

    assert one != two


def test_the_same_words_with_different_cards_is_a_different_shape() -> None:
    """ "Собрал те же три карточки" is half of what makes it the same thing."""
    one = repeating.shape_of("Draft a plan", "idea · a thought")
    two = repeating.shape_of("Draft a plan", "file · /tmp/x.py")

    assert one != two


def test_a_previous_question_is_not_a_card() -> None:
    """Counting it would make a shape out of how long a conversation was."""
    with_history = repeating.shape_of("Draft a plan", CONTEXT + "\nearlier · what did it do")

    assert with_history == repeating.shape_of("Draft a plan", CONTEXT)


def test_names_and_numbers_are_dropped_before_two_are_compared() -> None:
    """The third time is always about a different thing."""
    one = repeating.shape_of("draft 01M1X a plan", CONTEXT)
    two = repeating.shape_of("draft a plan", CONTEXT)

    assert one == two


# --- and when it is worth saying anything --------------------------------------------------------
def test_three_times_is_when_it_says_something() -> None:
    """Twice is a coincidence; four is a person who has given up expecting the console to notice."""
    asked = [("Draft a plan for the reader", CONTEXT)] * 3

    found = repeating.noticed(asked)

    assert found is not None
    assert found.times == 3
    assert found.asks == "Draft a plan for the reader"


def test_twice_says_nothing() -> None:
    assert repeating.noticed([("Draft a plan", CONTEXT)] * 2) is None


def test_a_shape_from_last_month_is_not_what_they_are_doing_now() -> None:
    """An offer about it arrives as a non-sequitur.

    The filler questions are all different shapes, so nothing among them repeats: what is being
    asserted is that the three older ones are not reached at all.
    """
    asked = [(f"question {one} of many", CONTEXT) for one in "abcdefghijkl"[: repeating.RECENT]]
    asked += [("Draft a plan", CONTEXT)] * 3

    assert repeating.noticed(asked) is None


def test_the_most_recent_of_them_is_what_the_process_is_filled_from() -> None:
    """«С полями, заполненными по тому, что делалось» — and the last time is the closest thing to
    what they would do next."""
    asked = [
        ("Draft a plan for the reader", CONTEXT),
        ("Draft a plan for the store", CONTEXT),
        ("Draft a plan for the parser", CONTEXT),
    ]

    found = repeating.noticed(asked)

    assert found is not None and found.asks == "Draft a plan for the reader"


def test_a_question_with_no_words_in_it_shapes_nothing() -> None:
    assert repeating.noticed([("01M1X 42", CONTEXT)] * 3) is None


# --- and the offer ---------------------------------------------------------------------------------
async def test_the_console_says_nothing_until_it_has_seen_it_three_times(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    for _ in range(2):
        await desk.create_block(
            thread_id=thread.id, kind="question", input="Draft a plan", thread_set_by="human"
        )

    assert json.loads((await routes.what_keeps_being_done()).body)["times"] == 0


async def test_it_offers_once_it_has(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    for what in ("the reader", "the store", "the parser"):
        block = await desk.create_block(
            thread_id=thread.id,
            kind="question",
            input=f"Draft a plan for {what}",
            thread_set_by="human",
        )
        await desk.set_block_context(block.id, CONTEXT)

    said = json.loads((await routes.what_keeps_being_done()).body)

    assert said["times"] == 3
    assert said["says"] == "draft a plan"
    assert said["asks"] == "Draft a plan for the parser"
    assert said["kinds"] == ["idea", "session"]


async def test_drawing_it_puts_a_step_per_card_kind_and_the_question(desk: Store) -> None:
    """«Уже собранный, с полями, заполненными по тому, что делалось.»"""
    back = await routes.draw_what_keeps_being_done(
        _a_form({"asks": "Draft a plan for the parser", "kinds": "idea,session"})
    )

    made = json.loads(back.body)["made"]
    assert len(made) == 3
    labels = {one.label for one in await desk.step_cards()}
    assert "the idea" in labels and "the session" in labels
    chosen = await desk.card_roles()
    assert sorted(chosen.values()) == ["action", "object", "object"]


async def test_the_question_is_in_the_step_that_asks_it(desk: Store) -> None:
    await routes.draw_what_keeps_being_done(
        _a_form({"asks": "Draft a plan for the parser", "kinds": "idea"})
    )

    said = await desk.card_fields()
    assert any(
        "Draft a plan for the parser" in value
        for fields in said.values()
        for value in fields.values()
    )


async def test_drawing_nothing_is_refused_rather_than_making_an_empty_process(
    desk: Store,
) -> None:
    back = await routes.draw_what_keeps_being_done(_a_form({"asks": "  ", "kinds": "idea"}))

    assert back.status_code == 400
    assert await desk.step_cards() == []


def test_it_offers_and_never_saves() -> None:
    """An arrangement this console kept by itself is a list somebody did not make, sitting where
    they look for the ones they did. Keeping it is the press afterwards."""
    board = (HERE / "agent_desk" / "web" / "templates" / "board.html").read_text(encoding="utf-8")
    script = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))
    body = code[
        code.index(
            "document.addEventListener('click', async (event) => {\n  if (event.target.closest('[data-not-again]'))"
        ) :
    ]
    body = body[: body.index("\n});\n")]

    assert "data-draw-again" in board
    assert "data-not-again" in board
    # Nothing here calls the route that saves a process under a name.
    assert "/workbench/template" not in body


def test_waving_it_away_stops_it_coming_back() -> None:
    """An offer that returns after being dismissed is one that stops being read."""
    script = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))
    body = code[code.index("async function noticeTheRepetition") :]
    body = body[: body.index("\n}\n")]

    assert "notAgain" in body


def test_it_is_asked_when_something_was_answered_and_not_on_a_clock() -> None:
    script = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))

    assert "if (settled > answeredSoFar) noticeTheRepetition();" in code
