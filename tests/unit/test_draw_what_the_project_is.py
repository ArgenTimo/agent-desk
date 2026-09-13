"""Draw what the project actually is (docs/stories/12).

"нарисуй мне схему базы данных текущего проекта" — asked with the words in the field and nothing
else, the honest answer was `cannot:`, which is the refusal working and the feature doing nothing.
"""

from __future__ import annotations

import pathlib
import tempfile
from collections.abc import AsyncIterator, Sequence

import pytest
from agent_desk import telling
from agent_desk.answer import classify, session
from agent_desk.store.repo import Store
from agent_desk.web import blocks

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk() -> AsyncIterator[Store]:
    with tempfile.TemporaryDirectory() as where:
        store = Store(pathlib.Path(where) / "agent-desk.db")
        await store.open()
        yield store
        await store.close()


class _Engine:
    """What a drawing run was given, and one reply to give back."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompt = ""
        self.add_dirs: list[pathlib.Path] = []

    async def __call__(
        self, prompt: str, *, add_dirs: Sequence[pathlib.Path] = (), **_: object
    ) -> AsyncIterator[str]:
        self.prompt = prompt
        self.add_dirs = list(add_dirs)
        yield self.reply


async def _asked(store: Store, said: str) -> str:
    thread = await store.create_thread(said)
    block = await store.create_block(
        thread_id=thread.id, kind="question", input=said, thread_set_by="human"
    )
    return block.id


# --- 1 · the drawing reads the project it is about ------------------------------------------------
async def test_with_nothing_chosen_it_is_the_desks_own_checkout(desk: Store) -> None:
    key, where = await blocks.checkout_for(desk, [])

    assert key.startswith("desk:")
    assert where == blocks.own_checkout()


async def test_a_chosen_project_is_read_where_it_was_last_seen(desk: Store) -> None:
    """A project with no session running still has the checkout it was last seen in (073)."""
    with tempfile.TemporaryDirectory() as there:
        await desk.note_project("origin:someone/shop", "shop", cwd=there)

        key, where = await blocks.checkout_for(desk, [], "origin:someone/shop")

        assert key == "origin:someone/shop"
        assert where == pathlib.Path(there)


async def test_a_project_that_is_not_on_this_machine_has_no_checkout(desk: Store) -> None:
    """Added by its address and never cloned, or cloned somewhere that has since gone. `None`
    rather than a directory that is not there."""
    await desk.note_project("origin:someone/gone", "gone", cwd="/nowhere/at/all")

    assert await blocks.checkout_for(desk, [], "origin:someone/gone") == (
        "origin:someone/gone",
        None,
    )
    assert (await blocks.checkout_for(desk, [], "origin:someone/never"))[1] is None


def test_the_prompt_says_where_the_project_is_and_how_to_read_it() -> None:
    asked = telling.shape_prompt("draw the database schema", where="/home/me/shop")

    assert "## The project" in asked
    assert "/home/me/shop" in asked
    assert "Read, Grep and Glob" in asked
    # Handed a checkout is not licence to invent: the refusal is still offered.
    assert "cannot: <what you would need to be shown>" in asked


def test_no_checkout_adds_no_heading() -> None:
    """A heading naming a directory that is not there reads as "look here" at nothing."""
    assert "## The project" not in telling.shape_prompt("draw a release process")


async def test_the_run_is_handed_the_checkout_to_read(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Named in the prompt and given to the engine, which is the read-only one every answer uses —
    three reading tools, nothing that writes (agent_desk/answer/session.py)."""
    engine = _Engine("object | orders | the orders table\nobject | users | the users table")
    monkeypatch.setattr(session, "stream_answer", engine)
    with tempfile.TemporaryDirectory() as there:
        await desk.note_project("origin:someone/shop", "shop", cwd=there)
        block_id = await _asked(desk, "нарисуй схему базы данных текущего проекта")
        block = await desk.block(block_id)
        assert block is not None

        await blocks._draw_it(desk, block, project="origin:someone/shop")

        assert engine.add_dirs == [pathlib.Path(there)]
        assert there in engine.prompt
    drawn = await desk.block(block_id)
    assert drawn is not None
    assert len(telling.read_drawn(drawn.answer or "")[1]) == 2


async def test_a_project_with_no_checkout_is_still_drawn_from_the_words(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A release process needs no files. Refusing every drawing about a project that is not here
    would refuse the one kind that never needed it."""
    engine = _Engine("action | run the tests | run them\naction | ship | ship it\n1 -> 2 : then")
    monkeypatch.setattr(session, "stream_answer", engine)
    block_id = await _asked(desk, "draw the release: tests, then ship")
    block = await desk.block(block_id)
    assert block is not None

    await blocks._draw_it(desk, block, project="origin:someone/never")

    assert engine.add_dirs == []
    drawn = await desk.block(block_id)
    assert drawn is not None
    assert len(telling.read_drawn(drawn.answer or "")[1]) == 2


async def test_a_refusal_about_a_project_that_is_not_here_says_that_is_why(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session, "stream_answer", _Engine("cannot: the schema files"))
    block_id = await _asked(desk, "draw the schema of the current project")
    block = await desk.block(block_id)
    assert block is not None

    await blocks._draw_it(desk, block, project="origin:someone/never")

    drawn = await desk.block(block_id)
    assert drawn is not None
    assert "someone/never is not checked out on this machine" in (drawn.answer or "")
    assert "the schema files" in (drawn.answer or "")


# --- 3 · any map, not two -------------------------------------------------------------------------
def test_the_classifier_is_told_a_map_is_a_drawing() -> None:
    """Described as "a sequence of steps with decisions in it", a request for a schema was as
    likely to be answered in prose as drawn."""
    said = classify.kind_prompt("нарисуй схему того, что может этот проект")

    assert "a *map* of what exists" in said
    assert "sequence of steps with decisions in it" not in said


def test_nothing_the_drawing_is_asked_with_names_a_kind_of_map() -> None:
    """The two examples the author gave are examples. A prompt that named them would draw those two
    well and the third one — a dependency map, a set of services — as whichever it resembled."""
    for asked in (
        telling.shape_prompt("draw it", where="/somewhere"),
        classify.kind_prompt("draw it"),
    ):
        lowered = asked.lower()
        for special in ("database", "feature matrix", "базы данных", "матриц"):
            assert special not in lowered, special
