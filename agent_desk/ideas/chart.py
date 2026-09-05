"""The pool as a picture: what depends on what, and what is already built.

Asked for as "было бы круто при отдельном отображении видеть матрицу/диаграмму всех идей... + те
идеи что уже реализованы тоже должны там отображаться, но с характерной визуализацией".

A list cannot show the thing that makes the links worth recording. Two ideas that each work on
their own, whose combination produces a third capability neither describes, are adjacent rows in a
list and nothing else — the relation is the information, and a list has nowhere to put it.

**Laid out here rather than in a browser.** There is no JavaScript build step in this repository
(docs/adr/0003) and a graph library is exactly the kind of thing that arrives with one. The layout
is the simplest one that reads correctly: a node sits one column to the right of everything it
needs, so dependencies always point left and the eye can follow them. Within a column, order is
the order the ideas were written.

That layout is not general. It is right for a pool of a few dozen thoughts with a handful of
dependencies each, which is what this is, and it degrades into "one tall column" rather than into
nonsense when there are no links at all.

**What is built is drawn, and drawn differently.** An idea that has been done leaves the column
but stays on the map, dimmed, because the value of a map is the shape of the whole thing — and
half the shape is what is already there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_desk.store.repo import Idea, IdeaLink

# The picture's geometry. Wide boxes because these are sentences, not identifiers.
BOX_WIDTH = 190
BOX_HEIGHT = 44
COLUMN_GAP = 90
ROW_GAP = 16
MARGIN = 20
# How deep a chain of dependencies is followed before it is treated as a cycle. Somebody who has
# written a loop into their notebook gets a picture rather than a hang.
MOST_COLUMNS = 12


@dataclass(frozen=True)
class Node:
    idea: Idea
    x: int
    y: int

    @property
    def done(self) -> bool:
        return self.idea.state == "done"


@dataclass(frozen=True)
class Edge:
    kind: str
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True)
class Chart:
    nodes: list[Node]
    edges: list[Edge]
    width: int
    height: int

    @property
    def empty(self) -> bool:
        return not self.nodes


def _depth(idea_id: str, needs: dict[str, list[str]], seen: frozenset[str]) -> int:
    """One more than the deepest thing this idea needs.

    `seen` is what makes a loop finite: an idea that ends up needing itself stops contributing
    depth rather than recursing forever. A notebook is allowed to contain a mistake.
    """
    if idea_id in seen or len(seen) > MOST_COLUMNS:
        return 0
    below = needs.get(idea_id, [])
    if not below:
        return 0
    return 1 + max(_depth(one, needs, seen | {idea_id}) for one in below)


def lay_out(ideas: Sequence[Idea], links: Sequence[IdeaLink]) -> Chart:
    """Where every idea and every line goes. Pure: no store, no template, no clock."""
    known = {idea.id: idea for idea in ideas}
    needs: dict[str, list[str]] = {}
    for link in links:
        if link.kind == "needs" and link.from_id in known and link.to_id in known:
            needs.setdefault(link.from_id, []).append(link.to_id)

    columns: dict[int, list[Idea]] = {}
    for idea in ideas:
        columns.setdefault(_depth(idea.id, needs, frozenset()), []).append(idea)

    placed: dict[str, Node] = {}
    for column, in_column in sorted(columns.items()):
        for row, idea in enumerate(in_column):
            placed[idea.id] = Node(
                idea=idea,
                x=MARGIN + column * (BOX_WIDTH + COLUMN_GAP),
                y=MARGIN + row * (BOX_HEIGHT + ROW_GAP),
            )

    edges: list[Edge] = []
    for link in links:
        one, other = placed.get(link.from_id), placed.get(link.to_id)
        if one is None or other is None:
            continue
        edges.append(
            Edge(
                kind=link.kind,
                x1=one.x,
                y1=one.y + BOX_HEIGHT // 2,
                x2=other.x + BOX_WIDTH,
                y2=other.y + BOX_HEIGHT // 2,
            )
        )

    width = max((node.x + BOX_WIDTH for node in placed.values()), default=0) + MARGIN
    height = max((node.y + BOX_HEIGHT for node in placed.values()), default=0) + MARGIN
    return Chart(
        nodes=sorted(placed.values(), key=lambda node: (node.x, node.y)),
        edges=edges,
        width=width,
        height=height,
    )
