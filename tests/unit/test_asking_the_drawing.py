"""Asking a drawing a question instead of running it (01M1XED1CPRAYRA5KNHF7VWKJB).

"Схема — это данные, а не картинка, и по ней можно отвечать на вопросы: какие шаги не пойдут без
человека, куда приведёт вот эта ветка, что случится, если этот шаг вернёт пусто, какие шаги вообще
недостижимы. Всё это чистые обходы графа поверх `process.py`. Ценность в том, что сегодня
единственный способ узнать — запустить и посмотреть."
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import process
from agent_desk.store.repo import BenchCard, Store
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


async def _a_bench(desk: Store, names: list[str]) -> None:
    await desk.keep_bench(
        [
            BenchCard(
                name=name,
                kind="step",
                card_id=name.partition(":")[2],
                label=name.partition(":")[2],
                x=0,
                y=at * 100,
                shown="hint",
                spent=False,
                ord=at,
            )
            for at, name in enumerate(names)
        ],
        thread_id="a",
    )
    for name in names:
        await desk.set_card_role(name, "action")


def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


async def test_it_says_what_would_never_run(desk: Store) -> None:
    """Today the only way to find that out is to run it and watch."""
    names = ["step:one", "step:two", "step:three"]
    await _a_bench(desk, names)
    await desk.tie_cards(from_name="step:one", to_name="step:two", kind="then", thread_id="a")
    await desk.tie_cards(from_name="step:two", to_name="step:three", kind="then", thread_id="a")

    said = json.loads((await routes.workbench_process(cards=",".join(names))).body)

    assert said["after"]["step:one"] == ["step:two", "step:three"]
    assert said["after"]["step:three"] == []


async def test_a_step_does_not_depend_on_itself(desk: Store) -> None:
    names = ["step:one", "step:two"]
    await _a_bench(desk, names)
    await desk.tie_cards(from_name="step:one", to_name="step:two", kind="then", thread_id="a")

    said = json.loads((await routes.workbench_process(cards=",".join(names))).body)

    assert "step:one" not in said["after"]["step:one"]


def test_it_is_the_same_walk_a_run_uses() -> None:
    """One answer to "what follows what", so this and the run cannot disagree."""
    cards = [
        process.Card(name="a", role="action", label="a"),
        process.Card(name="b", role="action", label="b"),
    ]
    lines = [process.Line(from_name="a", to_name="b", kind="then")]

    assert process.from_here("a", cards, lines) == ("a", "b")


def test_the_page_asks_what_it_already_has_rather_than_asking_again() -> None:
    source = _code()
    start = source.index("async function whatIfItStopped(")
    body = source[start : source.index("\n}\n", start)]

    assert "processSaid.after" in body
    assert "fetch(" not in body


def test_a_card_that_is_not_a_step_says_so_rather_than_showing_an_empty_list() -> None:
    """An empty list reads as "nothing depends on this", which is a different claim."""
    source = _code()
    start = source.index("async function whatIfItStopped(")
    body = source[start : source.index("\n}\n", start)]

    assert "This is not a step, so nothing runs after it." in body


def test_it_is_offered_only_on_a_step() -> None:
    source = _code()

    assert "isAStep(pin) ? [{ what: 'what if this stopped?'" in source
