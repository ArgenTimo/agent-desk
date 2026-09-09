"""What a request may do to the workbench, and how an answer that does it is read.

"На верстаке лежат разные карточки с информацией, я пишу запрос «подсвети те из них которые с
наибольшей вероятностью могут принести доход». Или другой запрос — «справа помести все карточки
идеи которых интересны простым пользователям, а слева те которые более интересны разработчикам»."

The difference from everything before it is one thing: the result of the request is not a new card
and not a paragraph, it is **a change to what is already there**. The workbench stops being only a
place things are put and becomes a thing you can arrange by talking.

## A fixed list, for the reason roles have five names and lines have five

"Модель должна отвечать не текстом про карточки, а действиями из фиксированного списка… свободная
формулировка «расположи покрасивее» не исполнима, и разбор её ответа превратится в угадайку."

Six, and they cover every example in the letter:

    mark   [colour] <numbers> <why>   point at some of the cards, and say why each
    sort   <side> <numbers> <what they have in common>
    clear                        take the marks off
    fold   <numbers>             show only their line
    open   <numbers>             show what they say
    take   <numbers>             take them off the workbench

`fold` and `open` are the two the letter opens with — "сверни разверни все (либо выделенные)
карточки" — and they belong to this list rather than to a control of their own for the same reason
the other three do: on a bench of thirty cards, "fold everything except the four about the
migration" is a sentence and not a sequence of thirty clicks. They also cost nothing to be wrong
about, which is the test everything in this list has to pass: a card folded by mistake is one press
from being open again.

"Поставить сюда" and "разложить по колонкам" are one action, not two — a column is a place, and
naming it is how somebody knows a minute later what is on the left. "Надписать" is that name, so it
arrives with the sort rather than as an action of its own.

What is deliberately absent is anything that *removes work*: nothing here joins two cards, drops
an idea, or starts anything. This is the cheapest branch in the whole idea pool — "ничего не
запускается, ничего не пишется, ничего не стоит, кроме одного вызова модели" — and it stays cheap by
not being able to do the expensive things.

`take` is the one that had to be argued rather than assumed, because this file used to refuse it —
and the refusal was wrong about its own repository. `041-bench-undo.sql` records *which cards are on
the bench* as part of the surface, so a card taken off comes back with the same press an arrangement
does. Nothing is deleted: the card is a row in the store and the conversation still holds it. What
changes is which of them are in front of somebody, which is precisely what this module is for —
"удали карточки такие-то и такие-то" asks for the thing the `×` on every card already does, and
asking for eleven of them in a sentence is the whole point of asking.

## The numbers are the ones the model was shown

A card is named by its number in the digest the question carried (`agent_desk/looking.py`). That is
what makes "возьми карточку с логами" work at all: the model can see which card is which, and can
point at one without copying a ULID back.

## Strict, and silent about what it could not read

A line that does not parse is skipped, and a reply where nothing parses produces nothing — which
the console renders as "it could not read that" rather than as an empty rearrangement. The same
rule `telling.read_shape` follows, for the same reason: a model asked for actions will sometimes
answer with a paragraph about the actions, and a reader that accepted anything would rearrange
somebody's bench from a sentence nobody meant as an instruction.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

# Where a sort may put things. Two sides and a middle, because the examples are all "these here and
# those there" — and because a model given a free choice of columns produces seven of them, which
# is a worse answer to "разложи" than three.
SIDES = ("left", "middle", "right")

# What a mark may be painted. "Закрась ярко жёлтым те карточки, что тебе больше всего нравятся, и
# т.д." — the "и т.д." is the request: a person wants to group cards by eye without moving them,
# and one colour cannot say "these and *those*".
#
# Three, and the two that are missing are missing on purpose. This console's palette says red means
# stopped or blocked and nothing else, and green means running; a model painting a card red would
# be putting a status on it that nothing behind the card supports, which is the fifth rule wearing
# a colour. These three carry no meaning anywhere else on the board, which is what makes them free
# for somebody to give one.
COLOURS = ("yellow", "blue", "violet")

# The longest a reason may be. It sits on a card under its label, so it is a line rather than a
# paragraph: a judgement nobody can read at a glance is a judgement nobody checks.
WHY_CHARS = 120


@dataclass(frozen=True)
class Marked:
    """One card the answer pointed at, and why it did.

    The reason is not decoration. "Модель, раскладывающая идеи по «принесёт доход», выносит
    суждение. По правилам этого проекта суждение показывается как суждение и рядом с основанием" —
    without it there is an arrangement nobody can trust or argue with.
    """

    name: str
    why: str
    # One of `COLOURS`, or "" for the ordinary mark. Not a free string: a colour nothing renders is
    # a mark somebody cannot see, and a colour this board uses for a status is a lie about one.
    colour: str = ""


@dataclass(frozen=True)
class Sorted:
    """One side of a sort: which cards go there, and what they have in common."""

    side: str
    names: list[str]
    what: str


@dataclass(frozen=True)
class Handling:
    """Everything one answer asked for. Empty means it asked for nothing this could read."""

    marked: list[Marked]
    sorted_: list[Sorted]
    clear: bool = False
    # Cards to show as a line only, and cards to open. Names rather than numbers, like everything
    # else here, so an arrangement applied to a bench that has changed since finds what it can and
    # quietly misses what is gone.
    folded: list[str] = field(default_factory=list)
    opened: list[str] = field(default_factory=list)
    # Cards to take off the surface. Not deleted: the card is a row in the store, the conversation
    # still holds it, and undo puts it back (041-bench-undo.sql).
    taken: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (
            self.marked or self.sorted_ or self.clear or self.folded or self.opened or self.taken
        )


def what_to_do(cards: Sequence[str]) -> str:
    """The instruction that goes under the workbench digest, when a request is a rearrangement.

    Written here rather than in the prompt builder because it is only true when there are cards to
    act on, and an instruction to answer in actions that arrives with no cards is an instruction to
    invent some.
    """
    return "\n".join(
        [
            "This is a request to change what is on the workbench, not a question about it.",
            "Answer with actions and nothing else — no preamble, no explanation, no closing line.",
            "",
            "One action per line, in one of these six shapes:",
            "",
            "  mark 3,7 why these two and not the others",
            "  mark yellow 1,2 why these are the yellow ones",
            "  sort left 1,4 what the ones on the left have in common",
            "  clear",
            "  fold 2,5,6",
            "  open 1",
            "  take 4",
            "",
            f"`sort` puts cards on one side: {', '.join(SIDES)}. `clear` takes every mark off.",
            f"A mark may name a colour: {', '.join(COLOURS)}. Use one when the request asks for",
            "colours or asks for two groups; leave it out and every mark looks the same.",
            "`fold` shows only a card's line; `open` shows what it says.",
            "`take` takes cards off the workbench. Nothing is deleted and one press of undo brings",
            "them back — but take a card off only where the request asks for it.",
            "",
            "Two rules matter more than the shape:",
            f"- Only the numbers above, 1 to {len(cards)}. A number that is not a card is ignored.",
            "- Every `mark` says why *those* cards, in a few words. A mark with no reason is an",
            "  opinion with nothing behind it, and it is shown to somebody who will want to argue",
            "  with it.",
        ]
    )


# `mark 3, 7 — because…` and `sort left 1,4 the developer ones`. The separator between the numbers
# and the words is anything or nothing: a model writes a dash, a colon, or neither, and refusing
# the reason over the punctuation in front of it would throw away the half that matters.
# The numbers are matched greedily and as a whole list. Written lazily — `[0-9][0-9,\s]*?` — the
# first digit satisfied it and "mark 1,3 because…" was read as card 1 with the reason ",3 because…".
_NUMBERS = r"(?:[0-9]+\s*,\s*)*[0-9]+"
# The colour is optional and comes before the numbers, which is the order somebody says it in and
# the order that keeps the old shape working unchanged: `mark 3,7 …` still parses as it always did.
_MARK = re.compile(
    rf"\Amark\s+(?:({'|'.join(COLOURS)})\s+)?({_NUMBERS})\s*[-—:.]?\s*(.*)\Z",
    re.IGNORECASE | re.DOTALL,
)
_SORT = re.compile(
    rf"\Asort\s+({'|'.join(SIDES)})\s+({_NUMBERS})\s*[-—:.]?\s*(.*)\Z",
    re.IGNORECASE | re.DOTALL,
)
_CLEAR = re.compile(r"\Aclear\b", re.IGNORECASE)
_FOLD = re.compile(rf"\Afold\s+({_NUMBERS})\s*\Z", re.IGNORECASE)
_OPEN = re.compile(rf"\Aopen\s+({_NUMBERS})\s*\Z", re.IGNORECASE)
_TAKE = re.compile(rf"\Atake\s+({_NUMBERS})\s*\Z", re.IGNORECASE)


def _named(said: str, on_bench: Sequence[str]) -> list[str]:
    """The card names those numbers stand for, in the order given, without repeats.

    A number that is not a card on the bench is dropped rather than raised on: a model that counted
    past the end has named nothing, and losing that one number is better than losing the line.
    """
    names: list[str] = []
    for part in said.replace(" ", "").split(","):
        if not part.isdigit():
            continue
        at = int(part)
        if 1 <= at <= len(on_bench) and on_bench[at - 1] not in names:
            names.append(on_bench[at - 1])
    return names


def read(reply: str, on_bench: Sequence[str]) -> Handling:
    """What the answer asked to be done, in card names rather than in numbers.

    `on_bench` is the cards in the order they were numbered for the model — the same order
    `looking.look` gave them.
    """
    marked: list[Marked] = []
    sorted_: list[Sorted] = []
    folded: list[str] = []
    opened: list[str] = []
    taken: list[str] = []
    clear = False
    for raw in reply.splitlines():
        said = raw.strip().lstrip("-*• ").strip()
        if not said:
            continue
        if _CLEAR.match(said):
            clear = True
            continue
        fold = _FOLD.match(said)
        if fold is not None:
            folded.extend(_named(fold.group(1), on_bench))
            continue
        opened_ = _OPEN.match(said)
        if opened_ is not None:
            opened.extend(_named(opened_.group(1), on_bench))
            continue
        take = _TAKE.match(said)
        if take is not None:
            taken.extend(_named(take.group(1), on_bench))
            continue
        sort = _SORT.match(said)
        if sort is not None:
            names = _named(sort.group(2), on_bench)
            if names:
                sorted_.append(
                    Sorted(
                        side=sort.group(1).lower(),
                        names=names,
                        what=sort.group(3).strip()[:WHY_CHARS],
                    )
                )
            continue
        mark = _MARK.match(said)
        if mark is not None:
            colour = (mark.group(1) or "").lower()
            why = mark.group(3).strip()[:WHY_CHARS]
            # One reason for the group, carried onto each card in it: the answer is "these two,
            # because X", and splitting that into two cards each saying X is what the person then
            # reads on the bench.
            marked.extend(
                Marked(name=name, why=why, colour=colour)
                for name in _named(mark.group(2), on_bench)
            )
    return Handling(
        marked=marked,
        sorted_=sorted_,
        clear=clear,
        folded=folded,
        opened=opened,
        taken=taken,
    )


# What the block stores, and what the page reads back to apply it.
#
# JSON rather than the lines the model wrote, because the lines are numbers and the numbers only
# mean anything beside the digest that produced them: a bench that has changed since would apply
# them to the wrong cards. Card names do not go stale that way — a name that is no longer on the
# bench is simply not found, which is the correct outcome.
def as_json(asked: Handling) -> str:
    return json.dumps(
        {
            "handling": {
                "marked": [
                    {"name": one.name, "why": one.why, "colour": one.colour} for one in asked.marked
                ],
                "sorted": [
                    {"side": one.side, "names": one.names, "what": one.what}
                    for one in asked.sorted_
                ],
                "clear": asked.clear,
                "folded": asked.folded,
                "opened": asked.opened,
                "taken": asked.taken,
            }
        }
    )


def read_json(said: str) -> Handling:
    """The actions back out of what a block stored, for the page and for anything that renders it.

    This module owns the shape, so this module reads it. `tests/unit/test_structure.py` names the
    modules allowed to parse JSON that is not one of Claude Code's on-disk formats, and the reason
    it is a list of paths rather than a rule is exactly this case: a program reading back something
    it wrote itself, in a shape it defines a dozen lines above.
    """
    try:
        found = json.loads(said).get("handling")
    except (ValueError, AttributeError):
        return Handling(marked=[], sorted_=[])
    # A `handling` key holding null, a number, a list — anything that is not the shape written
    # above. An older block, a failed run, a row somebody edited by hand: none of them rearrange
    # anything, and none of them is a reason to fail rendering the conversation.
    if not isinstance(found, dict):
        return Handling(marked=[], sorted_=[])
    return Handling(
        marked=[
            # A row written before colours existed has no key, and reads back as the ordinary mark.
            Marked(name=one["name"], why=one["why"], colour=one.get("colour", ""))
            for one in found.get("marked", [])
        ],
        sorted_=[
            Sorted(side=one["side"], names=list(one["names"]), what=one["what"])
            for one in found.get("sorted", [])
        ],
        clear=bool(found.get("clear")),
        # A block written before these existed has neither key, and reads back as asking for
        # nothing — which is what it asked for.
        folded=[str(one) for one in found.get("folded", [])],
        opened=[str(one) for one in found.get("opened", [])],
        taken=[str(one) for one in found.get("taken", [])],
    )


def as_words(asked: Handling) -> str:
    """What was done, for somebody reading the conversation rather than looking at the bench.

    A block whose answer is a blob of JSON says nothing to a person scrolling back through what
    they asked — and the point of storing the actions is that they can be applied *and* read.
    """
    said: list[str] = []
    if asked.clear and not asked.marked:
        said.append("Took the marks off.")
    # One line per reason rather than per card: the answer is "these two, because X", and a bench
    # showing X twice is what somebody then has to read twice.
    for why in dict.fromkeys(one.why for one in asked.marked):
        many = sum(1 for one in asked.marked if one.why == why)
        said.append(f"{many} card{'' if many == 1 else 's'}: {why}" if why else f"{many} marked")
    for side in asked.sorted_:
        many = len(side.names)
        said.append(
            f"{side.side}: {many} card{'' if many == 1 else 's'} — {side.what}".rstrip(" —")
        )
    # Counted rather than named. Folding is the one action whose result is plainly visible on the
    # bench, so what a reader of the conversation wants is how much of it happened.
    for what, names in (
        ("folded", asked.folded),
        ("opened", asked.opened),
        ("took off", asked.taken),
    ):
        if names:
            said.append(f"{what} {len(names)} card{'' if len(names) == 1 else 's'}")
    return "\n".join(said)
