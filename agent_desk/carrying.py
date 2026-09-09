"""A whole workbench as one document: cards, where they sit, and the lines between them.

*«Карточки, связи, поля, разрешения — одним файлом. "Вот всё, над чем я думал" становится одной
вещью, которую можно приложить к тикету, положить в репозиторий рядом с кодом или открыть через
месяц. Это сериализация уже существующих строк. И она же — резервная копия, которой сейчас нет
вообще.»*

## What travels and what deliberately does not

Card names, labels, positions, the folded-or-open state, and the lines. That is what a workbench
*is* — an arrangement somebody made — and it is enough to put the same arrangement back.

What does not travel is anything a card's body holds: no transcript, no file contents, no answer
text. Two reasons and either would be enough. A card's body is fetched from the store when it is
opened, so carrying it would be a second copy that goes stale; and a file somebody attaches to a
ticket is a file somebody else reads, which is the surface `docs/07-security.md` says redacts before
it renders. A label is what is already visible on a folded card across the room.

## A version, and what it is for

Not for migrating old files — there are none — but for refusing new ones clearly. A document from a
version this does not know is refused by name rather than half-read into a bench of nothing, which
is what an unversioned format does the first time it changes.

## Names, not ids

A card is `kind:id`, the same string every line, role and permission on the bench is keyed by. So a
document opened on another machine puts back every card whose row is there, says how many it could
not find, and does not invent the rest. A bench that quietly came back with eleven of fourteen
cards would be the fifth rule in a file format.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The shape of the document. Raised when what a file means changes, never when something is added
# that an older reader can ignore.
VERSION = 1

# How much of a bench one file may carry. A workbench is something a person arranged; two thousand
# cards is a bug upstream, and this is the same bound `keep_bench` is written under.
MOST_CARDS = 2000


@dataclass(frozen=True)
class Card:
    """One card as it travels: what it is, what it is called, and where it sat."""

    name: str
    kind: str
    label: str
    x: int
    y: int
    shown: str
    spent: bool
    came: str


@dataclass(frozen=True)
class Line:
    """One line between two cards."""

    from_name: str
    to_name: str
    kind: str
    says: str


@dataclass(frozen=True)
class Bench:
    """A whole workbench, and what could not be put back."""

    cards: list[Card]
    lines: list[Line]
    # Names in the document whose row is not on this machine. Counted rather than dropped: a bench
    # that quietly came back with eleven of fourteen cards is the fifth rule in a file format.
    missing: list[str]


def as_document(cards: list[Card], lines: list[Line], *, name: str = "") -> dict[str, Any]:
    """The file. Plain data, so `json.dumps` is the only thing between this and a file on disk."""
    return {
        "agent-desk": VERSION,
        "name": name,
        "cards": [
            {
                "name": one.name,
                "kind": one.kind,
                "label": one.label,
                "x": one.x,
                "y": one.y,
                "shown": one.shown,
                "spent": one.spent,
                "came": one.came,
            }
            for one in cards
        ],
        "lines": [
            {"from": one.from_name, "to": one.to_name, "kind": one.kind, "says": one.says}
            for one in lines
        ],
    }


def read_document(said: Any) -> Bench | None:
    """A document back into cards and lines, or `None` when it is not one.

    Refused whole rather than read as far as it goes. A file half-opened onto somebody's workbench
    is worse than one that would not open: the second is a message, the first is a mess they have
    to undo by hand.
    """
    if not isinstance(said, dict) or said.get("agent-desk") != VERSION:
        return None
    rows = said.get("cards")
    if not isinstance(rows, list):
        return None
    cards: list[Card] = []
    for row in rows[:MOST_CARDS]:
        if not isinstance(row, dict) or not str(row.get("name", "")).strip():
            continue
        kind, _, _rest = str(row["name"]).partition(":")
        cards.append(
            Card(
                name=str(row["name"]),
                kind=str(row.get("kind") or kind),
                label=str(row.get("label", ""))[:200],
                x=int(row.get("x", 20) or 0),
                y=int(row.get("y", 20) or 0),
                shown=str(row.get("shown", "hint")),
                spent=bool(row.get("spent")),
                came=str(row.get("came", ""))[:80],
            )
        )
    known = {one.name for one in cards}
    lines: list[Line] = []
    for row in said.get("lines", []) or []:
        if not isinstance(row, dict):
            continue
        from_name, to_name = str(row.get("from", "")), str(row.get("to", ""))
        # A line to a card the document does not carry is not a line. It would draw from nothing to
        # nothing and there would be no way to tell it from one whose card was taken off.
        if from_name in known and to_name in known:
            lines.append(
                Line(
                    from_name=from_name,
                    to_name=to_name,
                    kind=str(row.get("kind", "with")),
                    says=str(row.get("says", ""))[:120],
                )
            )
    return Bench(cards=cards, lines=lines, missing=[])
