"""The workbench as a diagram: the cards on it, and the relations between them.

Asked for as "отображение на верстаке не как просто блоки, а как диаграммы со всеми взаимосвязями".

A stack of cards says what each card is. It cannot say that *this* session is running in *that*
project, or that this idea needs that one — and when somebody has dragged four things onto the
bench in order to ask one question about them, the relation between them is usually the question.

Two rules, and they are what keep this from being decoration.

**Only relations this console already knows.** A session is in a project because its working
directory says so; an idea needs another because somebody said so (024-idea-links.sql). Nothing
here infers a relation from proximity or from words, which would be a picture of a guess.

**Only between cards that are on the bench.** A line to something you cannot see explains nothing,
so a relation with one end off the bench is not drawn at all.

The layout is the same one the idea map uses and for the same reason: containers on the left, what
they contain to the right of them, so a line is followed rather than traced.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_desk.ideas.chart import BOX_HEIGHT, BOX_WIDTH, COLUMN_GAP, MARGIN, ROW_GAP
from agent_desk.store.repo import Idea, IdeaLink


@dataclass(frozen=True)
class Piece:
    """One card on the bench, placed."""

    kind: str
    id: str
    label: str
    x: int
    y: int
    state: str = ""


@dataclass(frozen=True)
class Tie:
    """One relation between two cards, and the word for it."""

    says: str
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True)
class Bench:
    pieces: list[Piece]
    ties: list[Tie]
    width: int
    height: int

    @property
    def empty(self) -> bool:
        return not self.pieces


# Where each kind of card sits. A project contains an instance contains a session; an idea is its
# own thing and sits to the right of all of them, because that is where what-to-do-next goes.
COLUMN = {"project": 0, "instance": 1, "session": 2, "agent": 2, "blocker": 3, "idea": 4}


def _label(kind: str, card_id: str, rows: Sequence[object], ideas: dict[str, Idea]) -> str:
    if kind == "idea":
        idea = ideas.get(card_id)
        return idea.summary if idea else "an idea that has gone"
    if kind == "project":
        return card_id.split(":")[-1]
    for row in rows:
        session = getattr(row, "session", None)
        if session is None:
            continue
        if kind in ("session", "agent") and session.session_id == card_id:
            tail = getattr(row, "tail", None)
            title = getattr(tail, "title", None) if tail else None
            return str(title or session.name)
        if kind == "instance" and session.cwd == card_id:
            return str(session.project)
    return card_id.split("/")[-1][:40]


def lay_out(
    cards: Sequence[str],
    rows: Sequence[object],
    ideas: Sequence[Idea],
    links: Sequence[IdeaLink],
) -> Bench:
    """Where every card and every line goes. Pure: no store, no template, no clock.

    `cards` are `kind:id` strings, which is how the board's cards drag and how the workbench names
    what is on it.
    """
    by_id = {idea.id: idea for idea in ideas}
    placed: dict[str, Piece] = {}
    rows_in: dict[int, int] = {}

    for card in cards:
        kind, _, card_id = card.partition(":")
        # A pinned card may ask for its whole transcript; that is not part of its name here.
        card_id = card_id.removesuffix(":full")
        if not kind or not card_id or card in placed:
            continue
        column = COLUMN.get(kind, 4)
        line = rows_in.get(column, 0)
        rows_in[column] = line + 1
        idea = by_id.get(card_id)
        placed[card] = Piece(
            kind=kind,
            id=card_id,
            label=_label(kind, card_id, rows, by_id),
            x=MARGIN + column * (BOX_WIDTH + COLUMN_GAP),
            y=MARGIN + line * (BOX_HEIGHT + ROW_GAP),
            state=idea.state if idea else "",
        )

    ties: list[Tie] = []

    def tie(one: Piece, other: Piece, says: str) -> None:
        ties.append(
            Tie(
                says=says,
                x1=one.x + BOX_WIDTH,
                y1=one.y + BOX_HEIGHT // 2,
                x2=other.x,
                y2=other.y + BOX_HEIGHT // 2,
            )
        )

    # A session is in a project, and in a checkout of it. Read from the board's own rows, which is
    # where "which project is this session in" is already answered.
    for piece in placed.values():
        if piece.kind not in ("session", "agent"):
            continue
        for row in rows:
            session = getattr(row, "session", None)
            if session is None or session.session_id != piece.id:
                continue
            for other in placed.values():
                if other.kind == "project" and other.id == str(getattr(row, "project_key", "")):
                    tie(other, piece, "runs in")
                if other.kind == "instance" and other.id == session.cwd:
                    tie(other, piece, "runs in")

    # And an idea needs, or touches, another — but only when both ends are on the bench.
    for link in links:
        needs = placed.get(f"idea:{link.from_id}")
        needed = placed.get(f"idea:{link.to_id}")
        if needs is not None and needed is not None:
            tie(needed, needs, "needs" if link.kind == "needs" else "with")

    width = max((piece.x + BOX_WIDTH for piece in placed.values()), default=0) + MARGIN
    height = max((piece.y + BOX_HEIGHT for piece in placed.values()), default=0) + MARGIN
    return Bench(
        pieces=sorted(placed.values(), key=lambda piece: (piece.x, piece.y)),
        ties=ties,
        width=width,
        height=height,
    )
