"""A review pair that comes with the console (01M1XED1E7T6T9MA4BTB66D3SY).

"Шаблон из двух шагов: первый работает в своей копии, второй имеет только `read`, получает на вход
то, что вышло, и говорит «годится» или «вот что не так»… Это не новая механика: разрешения, память
шага и очередь уже есть. Это шаблон, который можно положить в коробку и который сразу делает
автономную работу заметно безопаснее."
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk import allowed, boxed, process
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

NAME = "make it, then check it"


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


def _the_pair() -> object:
    return boxed.named(NAME)


async def test_it_is_offered_on_a_console_nobody_has_touched(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An arrangement nobody has drawn is one nobody uses, which is the difference between "this is
    possible" and "this is what happens by default"."""
    monkeypatch.setattr(routes, "store", desk)

    said = json.loads((await routes.list_templates()).body)["templates"]

    assert [one["name"] for one in said] == [NAME]
    assert said[0]["boxed"] is True


async def test_saved_drawings_come_first_and_a_saved_name_wins(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Somebody who saved a drawing under the name of a boxed one meant theirs, and a console that
    reached past it to the built-in would be overruling a choice they made."""
    monkeypatch.setattr(routes, "store", desk)
    await desk.keep_template(name=NAME, steps=[], lines=[])

    said = json.loads((await routes.list_templates()).body)["templates"]

    assert said[0]["boxed"] is False


async def test_it_cannot_be_deleted_because_there_is_nothing_to_delete(desk: Store) -> None:
    """A `×` beside it would offer to remove something that comes back on the next reload — or,
    worse, look like it had not."""
    await desk.drop_template(NAME)

    assert boxed.named(NAME) is not None


async def test_the_second_step_may_only_read(desk: Store) -> None:
    """`read` means no worktree and no agent at all — the step is asked as a question. A reviewer
    that could write is a second author, and two authors and no reader is the arrangement this
    exists to replace."""
    pair = _the_pair()

    first, second = pair.steps  # type: ignore[attr-defined]
    assert first.leave == ("work",)
    assert second.leave == ("read",)
    assert "read" in allowed.ALLOWED and allowed.ALLOWED["read"].held == "enforced"


async def test_the_reader_is_fed_by_the_worker(desk: Store) -> None:
    """ "Получает на вход то, что вышло." A `then` line is what carries a step's result forward."""
    pair = _the_pair()

    (line,) = pair.lines  # type: ignore[attr-defined]
    assert (line.from_ord, line.to_ord) == (1, 2)
    assert line.kind in process.CARRIES


async def test_the_reader_is_told_not_to_fix_anything(desk: Store) -> None:
    """Its permission already stops it. Saying so as well is the same belt-and-braces every other
    permission gets in a briefing: an agent that knows it may not will not spend a turn trying."""
    pair = _the_pair()

    _, second = pair.steps  # type: ignore[attr-defined]
    assert "not fixing" in second.fields["do"]


async def test_both_steps_are_runnable_as_drawn(desk: Store) -> None:
    """A template that arrives incomplete is one somebody has to finish before they can press
    anything, which is the friction it was put in the box to remove."""
    pair = _the_pair()
    cards = [
        process.Card(name=f"step:{one.ord}", role=one.role, label=one.label, said=one.fields)
        for one in pair.steps  # type: ignore[attr-defined]
    ]
    lines = [process.Line(from_name="step:1", to_name="step:2", kind="then")]

    assert process.unfinished(cards) == {}
    assert process.ready_to_run(cards, lines) == ""


async def test_using_it_makes_fresh_cards_like_any_other(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Used by the same press and the same route: a second way to make a drawing would be a second
    thing to keep working."""
    monkeypatch.setattr(routes, "store", desk)

    made = json.loads((await routes.use_template(_a_form(name=NAME))).body)

    assert made["made"] is True
    assert len(made["cards"]) == 2


def _a_form(**fields: str) -> object:
    body = "&".join(f"{name}={value}" for name, value in fields.items()).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()
