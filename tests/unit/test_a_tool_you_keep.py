"""A card with behaviour in it, kept under a name (01M21KFV20764BZTNNSFQ743TH).

"Отдельная крупная фитча — конструктор инструментов. Уникальная карточка, в которую можно
закладывать разнообразный функционал: например заложить туда кнопку с промптом… Хранятся в списке
под проектами, слева снизу."

A button holds a request and a check holds a condition, and both die with the workbench they were
made on. Somebody who writes "декомпозируй" as a button writes it again in the next chat, and by
the fourth chat they stop bothering.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
BOARD = HERE / "agent_desk" / "web" / "templates" / "_board.html"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _a_form(**fields: str) -> object:
    body = "&".join(f"{name}={value}" for name, value in fields.items()).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()


def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


# --- what a tool is ------------------------------------------------------------------------------
async def test_a_tool_keeps_the_behaviour_and_not_the_card(desk: Store) -> None:
    """A card is a row plus where it sits plus what it is joined to, and none of those is worth
    keeping. What is worth keeping is the kind and the sentence."""
    made = await desk.keep_tool(name="decompose", kind="button", said="break this into parts")

    again = await desk.tool("decompose")
    assert made is not None and again is not None
    assert (again.kind, again.said) == ("button", "break this into parts")


async def test_only_a_kind_that_makes_a_card_may_be_kept(desk: Store) -> None:
    """The store refuses rather than the route, because it is the store that would otherwise hand
    back a tool nothing can put on a bench."""
    assert await desk.keep_tool(name="x", kind="buton", said="oops") is None
    assert await desk.keep_tool(name="x", kind="idea", said="a thought") is None
    assert await desk.tools() == []


async def test_a_tool_needs_a_name(desk: Store) -> None:
    assert await desk.keep_tool(name="   ", kind="button", said="anything") is None


async def test_keeping_over_a_name_replaces_it(desk: Store) -> None:
    """One "декомпозируй" per console. Two of them is a list where somebody has to remember which
    is the good one, and saving over is how a prompt got slightly wrong gets fixed."""
    await desk.keep_tool(name="decompose", kind="button", said="first try")

    await desk.keep_tool(name="decompose", kind="button", said="second try")

    kept = await desk.tools()
    assert len(kept) == 1
    assert kept[0].said == "second try"


# --- keeping one, from the card ------------------------------------------------------------------
async def test_a_button_is_kept_by_reading_the_card(desk: Store) -> None:
    """Read off the card rather than typed again: a tool whose prompt is a second copy of the
    button's is one that quietly stops matching the thing it was saved from."""
    button = await desk.add_button_card("run", "combine the chosen ideas")

    await routes.keep_a_tool(_a_form(card=f"button:{button.id}", name="combine"))

    kept = await desk.tool("combine")
    assert kept is not None and kept.said == "combine the chosen ideas"


async def test_a_check_can_be_kept_too(desk: Store) -> None:
    checked = await desk.add_check_card("no errors", "does not contain ERROR")

    await routes.keep_a_tool(_a_form(card=f"check:{checked.id}", name="clean"))

    kept = await desk.tool("clean")
    assert kept is not None and (kept.kind, kept.said) == ("check", "does not contain ERROR")


async def test_a_card_with_no_behaviour_in_it_is_not_a_tool(desk: Store) -> None:
    answer = await routes.keep_a_tool(_a_form(card="idea:01M1X", name="a thought"))

    assert "Only a button or a check" in answer.body.decode()
    assert await desk.tools() == []


async def test_a_card_that_is_gone_keeps_nothing(desk: Store) -> None:
    answer = await routes.keep_a_tool(_a_form(card="button:01M1NOSUCH", name="x"))

    assert "not here any more" in answer.body.decode()
    assert await desk.tools() == []


# --- and putting one on a bench -------------------------------------------------------------------
async def test_using_a_tool_makes_a_new_card_every_time(desk: Store) -> None:
    """Which is why the same tool can be on four workbenches at once with four different sets of
    lines, and why editing the card on one bench reaches neither the others nor the tool."""
    await desk.keep_tool(name="decompose", kind="button", said="break this into parts")

    first = json.loads((await routes.use_a_tool(_a_form(name="decompose"))).body)
    second = json.loads((await routes.use_a_tool(_a_form(name="decompose"))).body)

    assert first["id"] != second["id"]
    made = await desk.button_card(first["id"])
    assert made is not None and made.prompt == "break this into parts"


async def test_a_check_tool_makes_a_check_card(desk: Store) -> None:
    await desk.keep_tool(name="clean", kind="check", said="does not contain ERROR")

    made = json.loads((await routes.use_a_tool(_a_form(name="clean"))).body)

    assert made["kind"] == "check"
    assert (await desk.check_card(made["id"])).said == "does not contain ERROR"  # type: ignore[union-attr]


async def test_a_tool_that_is_not_there_says_so(desk: Store) -> None:
    answer = await routes.use_a_tool(_a_form(name="nothing"))

    assert "no tool by that name" in answer.body.decode()


async def test_forgetting_a_tool_leaves_the_cards_it_made(desk: Store) -> None:
    """They are copies. A card that vanished because somebody tidied a list is a workbench that
    changed while nobody was looking."""
    await desk.keep_tool(name="decompose", kind="button", said="break this into parts")
    made = json.loads((await routes.use_a_tool(_a_form(name="decompose"))).body)

    await routes.forget_a_tool(_a_form(name="decompose"))

    assert await desk.tools() == []
    assert await desk.button_card(made["id"]) is not None


# --- and where the list lives ---------------------------------------------------------------------
def test_the_list_is_under_the_projects() -> None:
    """ "Хранятся в списке под проектами, слева снизу." Not in a menu: a list nobody opened is a
    list nobody remembers they have."""
    markup = BOARD.read_text(encoding="utf-8")
    start = markup.index('action="/projects/attach"')

    assert 'id="kept-tools"' in markup[start:], "the tools are above the project controls"
    assert "showTools();" in _code()


def test_only_a_button_or_a_check_is_offered_the_keeping() -> None:
    """Keeping an idea card as a tool would be keeping a thing that is already kept, under a second
    name, in a second list."""
    source = _code()

    assert "pin.dataset.kind === 'button' || pin.dataset.kind === 'check'" in source
    assert "keep it as a tool" in source
