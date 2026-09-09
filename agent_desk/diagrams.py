"""A workbench as a diagram somebody can paste somewhere else.

*«Печать рабочих пространств в формате диаграмм.»*

The bench is already a diagram — that is what it is for — and it is a diagram inside one browser
tab. This is the same picture as text: pasteable into a pull request, a ticket, a document, a
message, and readable by everything that renders Mermaid without asking this console for anything.

## The shape says the role

Five roles and five outlines, so the picture carries what the bench carries. A diagram where an
Action and a Decision look alike is a diagram somebody has to read the labels of, which is what
having roles was for.

## Names never travel; labels do

A node's id is `n1`, `n2` — positional, meaningless, and safe. Card names are `kind:id` with a
colon in them, which Mermaid reads as syntax, and a diagram that broke on a card called
`idea:01M1…` would break on almost every card. The label is what a person reads and the id is what
the format needs, which is the ordinary division between the two.

Pure: cards and lines in, text out. What is on the bench is gathered where the store is.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# How long a label may be before it is cut. A diagram is read at a glance, and a node carrying a
# paragraph makes the whole picture unreadable rather than that one node.
LABEL_CHARS = 40

# The outline each role is drawn with. Mermaid's own shapes, chosen so the five are distinguishable
# at a glance rather than by reading: a diamond decides, a rounded box happens, a square acts.
SHAPES = {
    "action": ("[", "]"),
    "decision": ("{", "}"),
    "event": ("([", "])"),
    "object": ("[(", ")]"),
    "result": ("[/", "/]"),
}

# Anything Mermaid would read as syntax rather than as a word.
_SYNTAX = re.compile(r'["\[\]{}()<>|#;]')


@dataclass(frozen=True)
class Node:
    """One card in the picture."""

    name: str
    label: str
    role: str


@dataclass(frozen=True)
class Edge:
    """One line between two cards."""

    from_name: str
    to_name: str
    says: str = ""


def _label(said: str) -> str:
    words = " ".join(_SYNTAX.sub(" ", said).split())
    if len(words) > LABEL_CHARS:
        words = words[: LABEL_CHARS - 1] + "…"
    return words or "a card"


def as_mermaid(nodes: Sequence[Node], edges: Sequence[Edge]) -> str:
    """The diagram, as text.

    Top to bottom, because a process is read the way it runs and a wide diagram is one nobody can
    print. An empty bench produces the header and nothing else — a picture of nothing is the right
    picture of an empty bench, and refusing would leave somebody wondering which of the two it was.
    """
    at = {one.name: f"n{index + 1}" for index, one in enumerate(nodes)}
    said = ["flowchart TD"]
    for one in nodes:
        opened, closed = SHAPES.get(one.role, SHAPES["action"])
        said.append(f'    {at[one.name]}{opened}"{_label(one.label)}"{closed}')
    for edge in edges:
        # A line to a card that is not in the picture is not drawn. It would either invent a node
        # nobody put on the bench or point at nothing, and both are worse than the line's absence.
        if edge.from_name not in at or edge.to_name not in at:
            continue
        words = _label(edge.says) if edge.says.strip() else ""
        arrow = f'-- "{words}" -->' if words else "-->"
        said.append(f"    {at[edge.from_name]} {arrow} {at[edge.to_name]}")
    return "\n".join(said)
