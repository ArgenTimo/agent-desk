"""The pool as a picture: where every idea and every line goes (agent_desk/ideas/chart.py).

A pure function with no store, no template and no clock in it, which is why it can be tested by
reading coordinates rather than by rendering a page and hoping.
"""

from __future__ import annotations

import pytest
from agent_desk.ideas import chart
from agent_desk.store.repo import Idea, IdeaLink


def _idea(idea_id: str, state: str = "new") -> Idea:
    return Idea(
        id=idea_id,
        block_id=None,
        text=idea_id,
        summary=idea_id,
        state=state,  # type: ignore[arg-type]
        source_kind="typed",
        source_ref=None,
        context={},
        created_at=0,
    )


def _link(from_id: str, to_id: str, kind: str = "needs") -> IdeaLink:
    return IdeaLink(id=f"{from_id}->{to_id}", from_id=from_id, to_id=to_id, kind=kind, created_at=0)  # type: ignore[arg-type]


@pytest.mark.unit
def test_an_idea_sits_to_the_right_of_what_it_needs() -> None:
    """Dependencies point left, so the eye can follow them."""
    drawn = chart.lay_out([_idea("a"), _idea("b")], [_link("a", "b")])

    a = next(node for node in drawn.nodes if node.idea.id == "a")
    b = next(node for node in drawn.nodes if node.idea.id == "b")
    assert b.x < a.x
    assert len(drawn.edges) == 1


@pytest.mark.unit
def test_a_pool_with_no_links_is_one_column_rather_than_nonsense() -> None:
    drawn = chart.lay_out([_idea("a"), _idea("b"), _idea("c")], [])

    assert len({node.x for node in drawn.nodes}) == 1
    assert len({node.y for node in drawn.nodes}) == 3
    assert drawn.edges == []


@pytest.mark.unit
def test_a_loop_in_the_notebook_gets_a_picture_rather_than_a_hang() -> None:
    """A notebook is allowed to contain a mistake."""
    drawn = chart.lay_out(
        [_idea("a"), _idea("b"), _idea("c")],
        [_link("a", "b"), _link("b", "c"), _link("c", "a")],
    )

    assert len(drawn.nodes) == 3
    assert len(drawn.edges) == 3
    assert drawn.width > 0 and drawn.height > 0


@pytest.mark.unit
def test_what_is_built_stays_on_the_map_and_is_marked() -> None:
    """Half the shape of a pool is what is already there; a map that dropped it would be a map of
    the work that is left."""
    drawn = chart.lay_out([_idea("a"), _idea("b", state="done")], [_link("a", "b")])

    built = next(node for node in drawn.nodes if node.idea.id == "b")
    assert built.done
    assert not next(node for node in drawn.nodes if node.idea.id == "a").done


@pytest.mark.unit
def test_a_link_to_an_idea_that_is_not_drawn_is_skipped_rather_than_dangling() -> None:
    drawn = chart.lay_out([_idea("a")], [_link("a", "gone")])

    assert len(drawn.nodes) == 1
    assert drawn.edges == []


@pytest.mark.unit
def test_an_empty_pool_draws_nothing_and_says_so() -> None:
    drawn = chart.lay_out([], [])

    assert drawn.empty
    assert drawn.nodes == [] and drawn.edges == []


@pytest.mark.unit
def test_a_long_chain_stops_rather_than_running_away() -> None:
    """MOST_COLUMNS is the guard, and it is on depth rather than on the number of ideas."""
    ideas = [_idea(str(number)) for number in range(chart.MOST_COLUMNS + 6)]
    links = [_link(str(number), str(number + 1)) for number in range(chart.MOST_COLUMNS + 5)]

    drawn = chart.lay_out(ideas, links)

    assert len(drawn.nodes) == len(ideas)
    assert drawn.width < chart.MOST_COLUMNS * 10 * (chart.BOX_WIDTH + chart.COLUMN_GAP)
