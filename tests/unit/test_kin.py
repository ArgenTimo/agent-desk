"""Is this thought one that is already written down? (agent_desk/ideas/kin.py)

The failure this replaces is a list of near-duplicates. The failure it could introduce is worse —
two different thoughts filed as one, and the second gone from the list somebody reads — so most of
these assert that nothing was moved.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.ideas import kin
from agent_desk.store.repo import Store


@pytest.fixture
async def store(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    desk = Store(tmp_path / "agent-desk.db")
    await desk.open()
    yield desk
    await desk.close()


def _answers(reply: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(prompt: str) -> AsyncIterator[str]:
        yield reply

    monkeypatch.setattr(kin, "stream_answer", fake)


@pytest.mark.unit
def test_the_three_answers_and_everything_else_is_new() -> None:
    """`new` is the default and anything unparsable becomes it, because the wrong answer here
    hides somebody's thought inside somebody else's."""
    assert kin.read_kin("new", 3) == ("new", 0)
    assert kin.read_kin("same 2", 3) == ("same", 2)
    assert kin.read_kin("under 3", 3) == ("under", 3)
    assert kin.read_kin("UNDER 1", 3) == ("under", 1)

    for unusable in ("", "maybe?", "same", "under 0", "under 9", "same -1", "it is like idea 2"):
        assert kin.read_kin(unusable, 3) == ("new", 0), unusable


@pytest.mark.unit
async def test_a_repeat_is_hung_under_the_idea_it_repeats(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await store.create_idea(text_="add hotkeys", summary="add hotkeys", source_kind="typed")
    again = await store.create_idea(
        text_="we should have keyboard shortcuts",
        summary="keyboard shortcuts",
        source_kind="typed",
    )
    _answers("same 1", monkeypatch)

    assert await kin.place(store, again) == "same"

    moved = await store.idea(again.id)
    assert moved is not None and moved.parent_id == first.id
    # Nothing anybody wrote was touched: there is no statement in this program that writes
    # `idea.text` and this module does not add one (docs/05-ideas.md).
    assert moved.text == "we should have keyboard shortcuts"
    assert (await store.idea(first.id)).text == "add hotkeys"  # type: ignore[union-attr]


@pytest.mark.unit
async def test_a_part_of_a_bigger_idea_becomes_a_sub_idea(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    whole = await store.create_idea(
        text_="rework the console", summary="rework the console", source_kind="typed"
    )
    part = await store.create_idea(text_="and a grid", summary="and a grid", source_kind="typed")
    _answers("under 1", monkeypatch)

    assert await kin.place(store, part) == "under"
    assert (await store.idea(part.id)).parent_id == whole.id  # type: ignore[union-attr]


@pytest.mark.unit
async def test_an_idea_that_is_its_own_thing_is_left_exactly_where_it_is(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    await store.create_idea(text_="add hotkeys", summary="add hotkeys", source_kind="typed")
    other = await store.create_idea(
        text_="fix the sort", summary="fix the sort", source_kind="typed"
    )
    _answers("new", monkeypatch)

    assert await kin.place(store, other) == "new"
    assert (await store.idea(other.id)).parent_id is None  # type: ignore[union-attr]


@pytest.mark.unit
async def test_an_idea_somebody_has_touched_is_never_moved(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A state somebody set is a person saying what this card is, and this does not argue."""
    await store.create_idea(text_="add hotkeys", summary="add hotkeys", source_kind="typed")
    kept = await store.create_idea(text_="shortcuts", summary="shortcuts", source_kind="typed")
    await store.set_idea_state(kept.id, "kept")
    _answers("same 1", monkeypatch)

    assert "already touched it" in await kin.place(store, kept)
    assert (await store.idea(kept.id)).parent_id is None  # type: ignore[union-attr]


@pytest.mark.unit
async def test_an_unavailable_model_leaves_an_honest_duplicate(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Far smaller than the failure this must never cause, which is a capture that lost a thought."""
    await store.create_idea(text_="add hotkeys", summary="add hotkeys", source_kind="typed")
    again = await store.create_idea(text_="shortcuts", summary="shortcuts", source_kind="typed")

    async def broken(prompt: str) -> AsyncIterator[str]:
        raise kin.AnswerFailed("no model here")
        yield ""  # pragma: no cover

    monkeypatch.setattr(kin, "stream_answer", broken)

    assert await kin.place(store, again) == "new"
    assert (await store.idea(again.id)).parent_id is None  # type: ignore[union-attr]


@pytest.mark.unit
async def test_the_first_idea_in_an_empty_notebook_is_compared_with_nothing(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    only = await store.create_idea(text_="the first one", summary="the first", source_kind="typed")

    def never(*a: object, **k: object) -> None:  # pragma: no cover — reaching it is the failure
        raise AssertionError("a model was asked about an empty notebook")

    monkeypatch.setattr(kin, "stream_answer", never)

    assert "nothing to compare" in await kin.place(store, only)


@pytest.mark.unit
async def test_an_idea_is_never_filed_under_its_own_child(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A parent that is its own descendant renders forever."""
    parent = await store.create_idea(
        text_="the big one", summary="the big one", source_kind="typed"
    )
    child = await store.create_idea(text_="a part", summary="a part", source_kind="typed")
    await store.set_idea_parent(child.id, parent.id)
    _answers("under 1", monkeypatch)

    # The child is not offered as a candidate for its own parent at all.
    assert await kin.place(store, parent) in ("new", "new: nothing to compare it with")
    assert (await store.idea(parent.id)).parent_id is None  # type: ignore[union-attr]
