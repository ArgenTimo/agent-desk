"""A drawing said in words, and words read back as a drawing.

From the first user's feedback: *"менеджер собирает схему; кто-то другой должен её понять, не
открывая верстак. Схема должна уметь превращаться в описание процесса обычными словами — и
обратно: описание словами предлагает схему."*

Both directions, and they are not the same kind of thing.

**Drawing to words is a fact.** The order comes from the lines, the words come from the fields, and
turning one into the other is a function with one right answer. It is pure, here, and takes no
model call — a description that could come back differently on two afternoons would be no use for
the thing it is for, which is handing work to somebody who was not in the room.

**Words to a drawing is a guess.** There is no right answer to "what shape does this paragraph
describe", so it is a model call, it is rendered as a *proposal*, and nothing is put on anybody's
workbench until they say so. That is the same rule the meeting intake follows
(docs/10-meeting-intake.md) and the same rule the whole idea pool follows: a machine may propose,
a person disposes.

The parser below is the part that matters in that second direction. A model asked for a shape will
sometimes answer with a paragraph about the shape, and a reader that accepts anything would put a
drawing on the bench that nobody described.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from agent_desk import process, roles, ties


def as_words(cards: Sequence[process.Card], lines: Sequence[process.Line]) -> str:
    """The drawing as a description somebody can read without opening it.

    Pure and ordered: the steps in the order they run, each said as a sentence, with the ways out
    of a decision listed under it. Cards that are not steps are described where they feed
    something, because "the deploy log" on its own is not a line of a process — it is a thing one
    of the steps uses.
    """
    if not cards:
        return ""
    by_name = {card.name: card for card in cards}
    walked = process.order(cards, lines)
    said: list[str] = []
    number = 0

    for name in walked.steps:
        card = by_name.get(name)
        if card is None or card.role not in process.STEPS:
            continue
        number += 1
        said.append(f"{number}. {_one_step(card)}")
        for line in lines:
            if line.from_name != name or line.kind not in ("if", "when"):
                continue
            other = by_name.get(line.to_name)
            if other is None:
                continue
            word = "If" if line.kind == "if" else "When"
            what = line.says or ("the condition holds" if line.kind == "if" else "it happens")
            said.append(f"   - {word} {what}: {other.label or other.name}.")
        for feeds in process.feeding(name, cards, lines):
            if feeds.role in process.STEPS:
                continue
            said.append(f"   - Using {feeds.label or feeds.name}{_what_it_is(feeds)}.")

    if walked.tangled:
        said.append("")
        said.append(
            "Not in any order: "
            + ", ".join(by_name[one].label or one for one in walked.tangled if one in by_name)
            + " — they point at each other in a loop."
        )
    return "\n".join(said)


def _one_step(card: process.Card) -> str:
    """One step as a sentence, in the words its role was asked for."""
    role = roles.role_of(card.role)
    said = card.said
    if card.role == "action":
        what = (said.get("do") or "").strip()
        if not what:
            # Its name is not a description of it, and a document handed to somebody who was not
            # in the room must not read as though it were: this is the step an engine would stop
            # on, and the description says so in the same place.
            return f"{card.label or 'a step'} — not yet described."
        with_what = (said.get("using") or "").strip()
        return f"{what}." + (f" Using {with_what}." if with_what else "")
    if card.role == "decision":
        ask = (said.get("ask") or "").strip() or card.label
        return f"Decide: {ask}."
    if card.role == "event":
        awaits = (said.get("awaits") or "").strip() or card.label
        return f"Wait until {awaits}."
    return f"{role.says}: {card.label or card.name}."


def _what_it_is(card: process.Card) -> str:
    what = (card.said.get("what") or card.said.get("counts") or "").strip()
    return f" ({what})" if what else ""


# --- and the other way: words that propose a drawing --------------------------------------------

# One step per line, in a shape strict enough that a paragraph about the shape cannot be mistaken
# for the shape. `role | label | words` and nothing else.
_STEP = re.compile(r"\A(object|action|decision|event|result)\s*\|\s*([^|]{1,120})\|?(.*)\Z", re.I)
# `1 -> 2 : kind : words`, where the numbers are the steps above.
_LINE = re.compile(r"\A(\d+)\s*->\s*(\d+)\s*:\s*(\w+)\s*:?(.*)\Z")


def shape_prompt(text: str) -> str:
    """Ask for a shape, in a form that can be read rather than interpreted.

    The instruction against inventing steps is not decoration. A model asked to draw a process
    will happily add the two steps everybody's process has, and a person accepting the proposal
    would be accepting work they never described.
    """
    return "\n".join(
        [
            "Turn the description below into a process, using only what it actually says.",
            "",
            "Answer with lines and nothing else — no prose, no preamble, no explanation.",
            "",
            "First the steps, one per line, numbered by their order in your answer:",
            "  <role> | <short name> | <what it does>",
            "where <role> is one of: object, action, decision, event, result.",
            "",
            "Then the lines between them:",
            "  <from number> -> <to number> : <kind> : <words on the line>",
            "where <kind> is one of: then, if, when, makes, with.",
            "Use `if` for a way out of a decision and put the condition in the words.",
            "",
            "Do not invent steps the description does not mention. If it describes three things,",
            "answer with three steps. A step nobody asked for is worse than a short answer.",
            "",
            "## The description",
            text,
        ]
    )


def read_shape(reply: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """The steps and lines a reply describes, and nothing it merely mentions.

    Strict on purpose. A model asked for a shape will sometimes answer with a paragraph about the
    shape, and a reader that accepted anything would put a drawing on somebody's bench that nobody
    described. A line that does not parse is skipped rather than guessed at; a reply where nothing
    parses produces nothing, which renders as "it could not read that" instead of an empty bench.
    """
    steps: list[dict[str, str]] = []
    lines: list[dict[str, str]] = []
    for raw in reply.splitlines():
        said = raw.strip()
        if not said:
            continue
        # Lines first, and *before* any numbering is stripped off the front. A line begins with
        # the number of the step it leaves, and stripping leading digits to tidy up a numbered
        # list of steps turned every single line into unparseable rubbish — silently, because a
        # line that does not parse is skipped by design.
        line = _LINE.match(said)
        if line is not None:
            kind = line.group(3).lower()
            if ties.is_a_kind(kind):
                lines.append(
                    {
                        "from": line.group(1),
                        "to": line.group(2),
                        "kind": kind,
                        "says": line.group(4).strip()[:200],
                    }
                )
            continue
        # A step may arrive with the numbering a list usually has on it.
        said = said.lstrip("0123456789.） )").strip()
        step = _STEP.match(said)
        if step is not None:
            steps.append(
                {
                    "role": step.group(1).lower(),
                    "label": step.group(2).strip()[:120],
                    "words": step.group(3).strip()[:2000],
                }
            )
            continue
    # A line pointing at a step that is not there is a line nobody can draw. Dropped rather than
    # kept, because a drawing with a dangling arrow is harder to correct than one with none.
    within = range(1, len(steps) + 1)
    lines = [one for one in lines if int(one["from"]) in within and int(one["to"]) in within]
    return steps, lines


def words_for(role: str) -> str:
    """Which field a proposed step's words go into: the one its role needs.

    A proposal that put the description somewhere the role does not ask about would produce cards
    that look filled in and read as empty to everything else.
    """
    needed = [field.name for field in roles.fields_of(role) if field.needed]
    if needed:
        return needed[0]
    asked = roles.fields_of(role)
    return asked[0].name if asked else ""
