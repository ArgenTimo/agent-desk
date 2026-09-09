"""A workbench as a diagram somebody can paste elsewhere (01M1XAAJJY67X32T1762C6678K).

"Печать рабочих пространств в формате диаграмм."

The bench is already a diagram. This is the same picture as text — pasteable into a pull request, a
ticket or a message, and readable by everything that renders Mermaid without asking this console
for anything.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import diagrams, roles
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


def test_a_card_name_never_reaches_the_diagram() -> None:
    """`kind:id` has a colon in it, which Mermaid reads as syntax — a diagram that broke on a card
    called `idea:01M1…` would break on almost every card."""
    said = diagrams.as_mermaid(
        [diagrams.Node(name="idea:01M1X", label="a thought", role="action")], []
    )

    assert "idea:01M1X" not in said
    assert 'n1["a thought"]' in said


def test_the_shape_says_the_role() -> None:
    """A diagram where an Action and a Decision look alike is one somebody has to read the labels
    of, which is what having roles was for."""
    nodes = [
        diagrams.Node(name="a", label="do it", role="action"),
        diagrams.Node(name="b", label="is it?", role="decision"),
        diagrams.Node(name="c", label="it happened", role="event"),
    ]

    said = diagrams.as_mermaid(nodes, [])

    assert 'n1["do it"]' in said
    assert 'n2{"is it?"}' in said
    assert 'n3(["it happened"])' in said


def test_every_role_has_an_outline() -> None:
    """Five roles and five outlines. A role added without one would be drawn as an Action and read
    as a lie about what it is."""
    assert set(diagrams.SHAPES) == set(roles.ROLES)


def test_what_a_line_says_is_on_the_line() -> None:
    said = diagrams.as_mermaid(
        [
            diagrams.Node(name="a", label="a", role="action"),
            diagrams.Node(name="b", label="b", role="action"),
        ],
        [diagrams.Edge(from_name="a", to_name="b", says="when it is green")],
    )

    assert 'n1 -- "when it is green" --> n2' in said


def test_a_line_to_a_card_that_is_not_here_is_not_drawn() -> None:
    """It would either invent a node nobody put on the bench or point at nothing, and both are
    worse than the line's absence."""
    said = diagrams.as_mermaid(
        [diagrams.Node(name="a", label="a", role="action")],
        [diagrams.Edge(from_name="a", to_name="gone")],
    )

    assert "-->" not in said


def test_syntax_in_a_label_is_taken_out_rather_than_escaped() -> None:
    """A label somebody typed a bracket into is a label, not a diagram."""
    said = diagrams.as_mermaid(
        [diagrams.Node(name="a", label='read [the "log"] (twice)', role="action")], []
    )

    assert said.count("[") == 1 and said.count("]") == 1
    assert said.count('"') == 2


def test_a_long_label_is_cut_rather_than_carried() -> None:
    """A node carrying a paragraph makes the whole picture unreadable rather than that one node."""
    said = diagrams.as_mermaid([diagrams.Node(name="a", label="x" * 200, role="action")], [])

    assert len(said) < 120


def test_an_empty_bench_is_an_empty_diagram_rather_than_a_refusal() -> None:
    """A picture of nothing is the right picture of an empty bench, and refusing would leave
    somebody wondering which of the two it was."""
    assert diagrams.as_mermaid([], []) == "flowchart TD"


async def test_the_role_is_the_one_the_bench_and_the_run_use(desk: Store) -> None:
    """So the shape in the picture and the shape on the surface cannot disagree."""
    await desk.keep_bench(
        [
            BenchCard(
                name="step:one",
                kind="step",
                card_id="one",
                label="decide",
                x=0,
                y=0,
                shown="hint",
                spent=False,
                ord=0,
            )
        ],
        thread_id="a",
    )
    await desk.set_card_role("step:one", "decision")

    said = json.loads((await routes.the_workbench_as_a_diagram(thread="a")).body)

    assert 'n1{"decide"}' in said["said"]
    assert said["cards"] == 1


def test_it_is_shown_rather_than_downloaded() -> None:
    """What somebody does with this is paste it, and a file they have to open first is a step in
    the way."""
    source = CONSOLE.read_text(encoding="utf-8")
    start = source.index("async function showTheDiagram(")
    body = source[start : source.index("\n}\n", start)]

    assert "text.select()" in body
    assert "link.download" not in body
