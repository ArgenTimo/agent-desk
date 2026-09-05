"""The workbench as a diagram: what is on it, and only the relations both ends of which are.

A line to something you cannot see explains nothing, so most of these assert that a line was not
drawn (agent_desk/ideas/bench.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from agent_desk.ideas import bench
from agent_desk.store.repo import Idea, IdeaLink


@dataclass
class _Session:
    session_id: str
    cwd: str
    name: str
    project: str


@dataclass
class _Row:
    session: _Session
    project_key: str
    tail: None = None


def _idea(idea_id: str, summary: str, state: str = "new") -> Idea:
    return Idea(
        id=idea_id,
        block_id=None,
        text=summary,
        summary=summary,
        state=state,  # type: ignore[arg-type]
        source_kind="typed",
        source_ref=None,
        context={},
        created_at=0,
    )


ROW = _Row(_Session("s-1", "/repo", "biba", "agent-desk"), "origin:acme/api")


@pytest.mark.unit
def test_a_session_and_the_project_it_runs_in_are_joined() -> None:
    drawn = bench.lay_out(["project:origin:acme/api", "session:s-1"], [ROW], [], [])

    assert {piece.kind for piece in drawn.pieces} == {"project", "session"}
    assert [tie.says for tie in drawn.ties] == ["runs in"]
    # Containers on the left, what they contain to the right, so a line is followed not traced.
    project = next(piece for piece in drawn.pieces if piece.kind == "project")
    session = next(piece for piece in drawn.pieces if piece.kind == "session")
    assert project.x < session.x


@pytest.mark.unit
def test_a_relation_with_one_end_off_the_bench_is_not_drawn() -> None:
    drawn = bench.lay_out(["session:s-1"], [ROW], [], [])

    assert len(drawn.pieces) == 1
    assert drawn.ties == []


@pytest.mark.unit
def test_two_ideas_on_the_bench_show_which_needs_which() -> None:
    ideas = [_idea("i1", "the parser"), _idea("i2", "the cache")]
    links = [IdeaLink(id="l", from_id="i2", to_id="i1", kind="needs", created_at=0)]

    drawn = bench.lay_out(["idea:i1", "idea:i2"], [], ideas, links)

    assert [tie.says for tie in drawn.ties] == ["needs"]
    assert {piece.label for piece in drawn.pieces} == {"the parser", "the cache"}


@pytest.mark.unit
def test_a_pinned_card_asking_for_its_whole_transcript_is_still_that_card() -> None:
    """`session:s-1:full` is the same card with a flag on it, not a card called `s-1:full`."""
    drawn = bench.lay_out(["session:s-1:full"], [ROW], [], [])

    (piece,) = drawn.pieces
    assert piece.id == "s-1"
    assert piece.label == "biba"


@pytest.mark.unit
def test_an_empty_bench_draws_nothing_and_says_so() -> None:
    drawn = bench.lay_out([], [], [], [])

    assert drawn.empty
    assert drawn.width == bench.MARGIN and drawn.height == bench.MARGIN


@pytest.mark.unit
def test_an_idea_that_has_gone_is_named_rather_than_left_blank() -> None:
    drawn = bench.lay_out(["idea:vanished"], [], [], [])

    (piece,) = drawn.pieces
    assert "has gone" in piece.label


@pytest.mark.unit
def test_the_same_card_twice_is_one_card() -> None:
    drawn = bench.lay_out(["session:s-1", "session:s-1"], [ROW], [], [])

    assert len(drawn.pieces) == 1
