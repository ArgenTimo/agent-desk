"""When the console cannot tell, it asks instead of starting agents
(01M1ZYJCR7ZVNM6ACXDN0RBSRM).

"Осторожно с ценой ошибки: неправильно понятый вопрос стоит одного лишнего ответа, неправильно
понятая просьба «сделай проект» стоит пяти агентов. Чем дороже ветка, тем выше должна быть
уверенность и тем скорее нужно спросить, а не догадываться."

The tie-breaks already pushed the error to the cheap side — unsure between an idea and an
instruction, answer idea. But the choice was still made for the person. This is the seventh answer,
and it does nothing until they press one.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.answer import classify
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
BLOCKS_HTML = HERE / "agent_desk" / "web" / "templates" / "_blocks.html"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


async def _a_block(store: Store, kind: str = "question") -> object:
    thread = await store.create_thread("a chat")
    return await store.create_block(
        thread_id=thread.id, kind=kind, input="do the thing", thread_set_by="human"
    )


# --- the seventh answer -----------------------------------------------------------------------------
def test_the_classifier_can_say_it_could_not_tell() -> None:
    assert classify.read_kind("unsure") == "unsure"


def test_it_is_offered_only_against_the_expensive_branches() -> None:
    """Asking about a cheap branch costs more attention than getting it wrong: `draw`, `show` and
    `arrange` are one model call, undone in one press."""
    asked = classify.kind_prompt("do the thing")

    assert "only for the expensive ones" in asked
    assert "a vague question is" in asked, "nothing stops it firing on every unclear line"


def test_the_scale_of_confidence_is_still_stated() -> None:
    asked = classify.kind_prompt("do the thing")

    assert "How sure you have to be depends on what it costs to be wrong" in asked


# --- the branch that does nothing ---------------------------------------------------------------------
async def test_it_runs_nothing_and_says_why(desk: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    block = await _a_block(desk)

    async def cannot_tell(_text: str, **_how: object) -> str:
        return "unsure"

    monkeypatch.setattr(blocks.classifier, "kind", cannot_tell)
    ran = []
    monkeypatch.setattr(blocks, "_classify_and_answer", lambda *a, **k: ran.append(1))

    await blocks._work(desk, block, [], classify=False)  # type: ignore[arg-type]

    again = await desk.block(block.id)
    assert again is not None
    assert again.kind == "unsure"
    assert "nothing has run" in (again.answer or "")
    assert ran == []


# --- and the choice --------------------------------------------------------------------------------
def test_the_block_offers_the_readings_it_could_not_choose_between() -> None:
    """Four and not seven. The cheap branches are not offered because asking about one of those is
    the more expensive mistake."""
    markup = BLOCKS_HTML.read_text(encoding="utf-8")
    start = markup.index('block.kind == "unsure"')
    offered = markup[start : markup.index("{% endif %}", start)]

    for name in ("question", "idea", "instruction", "master"):
        assert f'("{name}",' in offered
    for cheap in ("drawing", "showing", "handling"):
        assert cheap not in offered, cheap


async def test_pressing_one_does_that_one(desk: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    block = await _a_block(desk, kind="unsure")
    done = []

    async def wrote(*_a: object, **_k: object) -> None:
        done.append("idea")

    monkeypatch.setattr(blocks, "record_idea", wrote)

    await blocks.take_it_as(desk, block, [], "idea")  # type: ignore[arg-type]

    again = await desk.block(block.id)
    assert again is not None and again.kind == "idea"
    assert done == ["idea"]


async def test_the_console_cannot_be_asked_to_stay_unsure(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Choosing "unsure" is what the block is already showing."""
    block = await _a_block(desk, kind="unsure")

    await blocks.take_it_as(desk, block, [], "unsure")  # type: ignore[arg-type]

    again = await desk.block(block.id)
    assert again is not None and again.kind == "unsure"


async def test_a_kind_this_console_does_not_have_does_nothing(desk: Store) -> None:
    block = await _a_block(desk, kind="unsure")

    await blocks.take_it_as(desk, block, [], "nonsense")  # type: ignore[arg-type]

    again = await desk.block(block.id)
    assert again is not None and again.kind == "unsure"


async def test_only_a_block_that_asked_can_be_answered_this_way(desk: Store) -> None:
    """A route that could re-run any block as anything would be a way to start an agent from a
    question somebody asked yesterday, which is what the asking exists to prevent."""
    block = await _a_block(desk, kind="question")

    class Request:
        async def body(self) -> bytes:
            return b"kind=instruction"

        headers = {"content-type": "application/x-www-form-urlencoded"}  # noqa: RUF012

    answer = await routes.say_what_was_meant(block.id, Request())  # type: ignore[arg-type]

    assert answer.status_code == 404
    again = await desk.block(block.id)
    assert again is not None and again.kind == "question"
