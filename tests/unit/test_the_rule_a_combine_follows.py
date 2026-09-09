"""What "put these two together" means, and where that is decided.

"В алхимии вода + огонь = пар. В работе две карточки + вопрос = новый документ. Правило — это то,
что превращает пару в третье, и оно должно быть видимым и сменяемым: одна и та же пара в разных
правилах даёт разное."

The gesture already existed and asked one hardcoded thing. That is fine for the first combine
somebody tries and wrong for the second: two cards put together to draft a document and the same
two put together to find what they disagree about are one gesture and two questions.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk import combining
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


def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


# --- the rule itself --------------------------------------------------------------------------
def test_saying_nothing_is_the_console_s_own_rule() -> None:
    """A bench nobody has told anything still combines, and asks what the console documents."""
    assert combining.rule("") == combining.DEFAULT
    assert combining.rule("   \n ") == combining.DEFAULT


def test_a_rule_somebody_set_is_what_is_asked() -> None:
    assert combining.rule("  find what they disagree about  ") == "find what they disagree about"


def test_too_much_is_trimmed_rather_than_refused() -> None:
    """Somebody who pasted a document gets a rule that is too long by the end and still works,
    which beats a gesture that stops working until they go and edit it."""
    said = combining.rule("x" * (combining.MOST_CHARS + 500))

    assert len(said) == combining.MOST_CHARS


# --- and where it lives ------------------------------------------------------------------------
async def test_a_bench_keeps_its_own_rule(desk: Store) -> None:
    """Per workbench, not per pair: "иначе на каждое соединение придётся объяснять заново"."""
    await desk.combine_with("t1", "draft a document from them")
    await desk.combine_with("t2", "find what they disagree about")

    assert await desk.combining("t1") == "draft a document from them"
    assert await desk.combining("t2") == "find what they disagree about"


async def test_clearing_it_is_the_same_as_never_having_set_it(desk: Store) -> None:
    """Two spellings of "the default" is one that somebody eventually has to reconcile."""
    await desk.combine_with("t1", "something else")

    await desk.combine_with("t1", "   ")

    assert await desk.combining("t1") == ""
    assert combining.rule(await desk.combining("t1")) == combining.DEFAULT


async def test_a_bench_that_was_never_told_says_so(desk: Store) -> None:
    assert await desk.combining("nobody") == ""


# --- and that the page does not hold a second copy of it ----------------------------------------
def test_the_page_does_not_carry_the_wording() -> None:
    """A copy in the page would be a second answer to "what does combining mean", and the two
    would part company the first time one of them moved."""
    source = _code()

    assert "HOW_TO_COMBINE" not in source
    assert "Make one thing out of these two" not in source
    assert "text:" not in _body_of("combine"), "the drag still sends words of its own"


def _body_of(name: str) -> str:
    source = _code()
    start = source.index(f"function {name}(")
    return source[start : source.index("\n}\n", start)]


def test_the_rule_is_read_where_the_gesture_is_answered() -> None:
    route = (HERE / "agent_desk" / "web" / "routes.py").read_text(encoding="utf-8")

    assert "typed = combining.rule(await store.combining(" in route


def test_it_can_be_read_before_it_is_used_and_changed() -> None:
    """ "Оно должно быть видимым и сменяемым." A tooltip is where somebody looks to find out what a
    control does, so it is where "what will this ask" belongs; the menu item is the other half."""
    assert 'data-add="combining"' in BOARD.read_text(encoding="utf-8")
    assert "function howCombiningWorks(" in _code()
    assert "function sayWhatCombiningAsks(" in _code()
    assert "if (name === 'mix') sayWhatCombiningAsks();" in _code()


async def test_the_same_pair_under_two_rules_asks_two_things(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole claim of the idea, and the reason a rule is a thing at all. Asserted against what
    the route hands to `submit`, because that is what the model is actually sent."""
    asked: list[str] = []
    thread = await desk.create_thread("a chat")

    async def caught(store: Store, typed: str, rows: object, **rest: object) -> object:
        asked.append(typed)
        return await desk.create_block(
            thread_id=thread.id, kind="question", input=typed, thread_set_by="human"
        )

    monkeypatch.setattr(routes.block_runs, "submit", caught)
    monkeypatch.setattr(routes, "board", lambda: ([], ""))

    for rule in ("draft a document from them", "find what they disagree about"):
        await desk.combine_with(thread.id, rule)
        await routes.ask(_a_form(thread=thread.id, made_from="idea%3Aa%2Cidea%3Ab"))

    assert asked == ["draft a document from them", "find what they disagree about"]


def _a_form(**fields: str) -> object:
    body = "&".join(f"{name}={value}" for name, value in fields.items()).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()
