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

import json
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
# `1 -> 2 : whatever it is called`. Tried only after the form above has failed to name one of the
# process kinds, so "1 -> 2 : then" is still a `then` and not a relation called "then".
_NAMED = re.compile(r"\A(\d+)\s*->\s*(\d+)\s*:\s*(.+)\Z")
# The one-line refusal: `cannot: <why>`. It exists so that "I have not been shown that" has a way
# of arriving that is not an empty answer — see `draw_prompt`.
_CANNOT = re.compile(r"\Acannot\s*:\s*(.+)\Z", re.I)


def shape_prompt(text: str, seen: Sequence[str] = ()) -> str:
    """Ask for a drawing, in a form that can be read rather than interpreted.

    Two vocabularies, and the model picks the one that fits what was asked. Five process words
    draw a process and are useless for anything else — *"таблица — не Action, «внешний ключ» — не
    «then»"* — so a request to draw a database schema, a set of services, or anything else somebody
    is looking at gets things and named relations instead, where the label on the line is what the
    relation is called (agent_desk/ties.py).

    The instruction against inventing is not decoration, and it is now two instructions. A model
    asked to draw a process will happily add the two steps everybody's process has, and a person
    accepting the proposal would be accepting work they never described. A model asked to draw "our
    database" will draw a database — a plausible one, from memory, of a schema it has never seen —
    and that one is worse, because it is not a wrong summary of something true but a picture of
    something that does not exist. So `cannot:` is offered as an answer, and what can be seen is
    listed under it: everything else is off limits.
    """
    lines = [
        "Draw what is described below, using only what it actually says and what you are shown.",
        "",
        "Answer with lines and nothing else — no prose, no preamble, no explanation.",
        "",
        "First the cards, one per line, numbered by their order in your answer:",
        "  <role> | <short name> | <what it is or does>",
        "where <role> is one of: object, action, decision, event, result.",
        "Anything that is a thing rather than a step is an object.",
        "",
        "Then the lines between them, in one of two forms.",
        "",
        "For a process — work happening in an order:",
        "  <from number> -> <to number> : <kind> : <words on the line>",
        "where <kind> is one of: then, if, when, makes, with.",
        "Use `if` for a way out of a decision and put the condition in the words.",
        "",
        "For anything else — things and how they relate:",
        "  <from number> -> <to number> : <what the relation is called>",
        "such as `foreign key`, `deploys to`, `owned by`. Use the name the thing itself uses.",
        "",
        "Do not invent cards the description does not mention. If it describes three things,",
        "answer with three cards. A card nobody asked for is worse than a short answer.",
        "",
        "Never draw from memory. If you are asked for something you have not been shown — a",
        "schema, a set of services, a file you cannot see — answer with one line:",
        "  cannot: <what you would need to be shown>",
        "A plausible drawing of something you have not seen is a lie that looks like an answer.",
        "",
        "## The description",
        text,
    ]
    if seen:
        lines += ["", "## What you can see", *seen]
    return "\n".join(lines)


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
        if line is not None and ties.is_a_kind(line.group(3).lower()):
            lines.append(
                {
                    "from": line.group(1),
                    "to": line.group(2),
                    "kind": line.group(3).lower(),
                    "says": line.group(4).strip()[:200],
                }
            )
            continue
        # Not one of the process words, so the whole of it is the relation's name. Read after the
        # five and not before, or "1 -> 2 : then" would be a relation called "then".
        named = _NAMED.match(said)
        if named is not None:
            lines.append(
                {
                    "from": named.group(1),
                    "to": named.group(2),
                    "kind": "named",
                    "says": named.group(3).strip()[:200],
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


def read_cannot(reply: str) -> str:
    """What the drawing would have needed to be shown, or "" when it drew something.

    The one thing a model is allowed to answer instead of a drawing, and the reason it exists is
    the one constraint this branch cannot enforce any other way: *"рисовать по тому, что модель
    ВИДИТ… Схема, нарисованная по памяти, выглядит правдоподобно и является выдумкой."* Nothing
    downstream can tell a drawing of a real schema from a drawing of a plausible one, so the only
    place the distinction can be made is where the drawing is not made.
    """
    for raw in reply.splitlines():
        found = _CANNOT.match(raw.strip())
        if found is not None:
            return found.group(1).strip()[:200]
    return ""


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


# --- a refusal, said so it cannot be scrolled past ------------------------------------------------
# "Если невозможно получить тот результат, что я хочу, из-за технического устройства проекта или
# других причин — всё это указывается в новых карточках систем-блоках (они должны особенно страшно
# выглядеть визуально, ярко-красные)."
#
# "Это самая важная часть всей идеи и она шире проверки: консоли нужен способ сказать «нет, и вот
# почему» так, чтобы это нельзя было пролистать. Сегодня отказ выглядит как обычный ответ, а
# значит читается как обычный ответ."
#
# What a run reports when it fails is written for whoever wrote the runner: "the run exited 4",
# "no answer within 180s", "needs_toolchain: claude is not on PATH". Each is true and none of them
# says what to do, which is the half a person needs at the moment something has stopped.
#
# So a failure is turned into two things: what happened, and what would change it. The mapping is
# a list of the failures this program can actually produce — everything else keeps its own words,
# because inventing a next step for a failure nobody has seen is exactly the guess CLAUDE.md's
# fifth rule forbids.
_STOPPED: tuple[tuple[str, str, str], ...] = (
    (
        "the day's budget is spent",
        "The day's budget for asking is spent.",
        "AGENT_DESK_DAILY_USD raises the ceiling, and 0 switches it off.",
    ),
    (
        "needs_toolchain",
        "The answer engine is not on this machine.",
        "`claude` has to be on PATH for this console to ask anything.",
    ),
    (
        "rate limit",
        "The model is rate limited.",
        "It comes back on its own; asking again now costs another refusal.",
    ),
    (
        "usage limit",
        "The account is out of budget.",
        "It comes back when the limit resets.",
    ),
    (
        "no answer within",
        "The run took longer than it is allowed to.",
        "AGENT_DESK_ANSWER_TIMEOUT_SECONDS gives it longer; a question about a whole repository "
        "usually wants a card dropped in rather than more time.",
    ),
)


def stopped(error: str) -> tuple[str, str]:
    """What stopped, and what would change it — or the original words and nothing.

    Two strings rather than one, because they are read at different moments: the first is what
    somebody sees without opening anything, and the second is what they do about it. A failure
    this list has not met keeps its own words and offers no next step, which reads as "something
    went wrong and this console does not know what to suggest" — the honest answer, and a visibly
    different one from the four it does know.
    """
    said = error.lower()
    for shape, what, act in _STOPPED:
        if shape in said:
            return what, act
    return error.strip() or "The run stopped without saying why.", ""


# --- what the console decided a message was ------------------------------------------------------
# "Если консоль решила, что это «сделай проект», человек должен это увидеть и успеть сказать «нет,
# это был вопрос» — до того, как поднялись агенты."
#
# The decision was already recorded before anything expensive started; what was missing is that
# nobody was told. A block carried its kind as a CSS class, which is a fact about the markup.
#
# `question` is deliberately absent. It is what an unread line is taken to be and what most lines
# are, so saying it on every message would be a sentence people learn to skip — and this line only
# earns its place by appearing when something less obvious was decided.
_TAKEN_AS = {
    "idea": "taken as a thought, and written down",
    "instruction": "taken as an instruction for an agent",
    "master": "taken as a job for this console itself",
    "handling": "taken as a change to the workbench",
    "showing": "taken as a request to fetch these and put them on the workbench",
    "running": "taken as: run what is on the workbench, against this",
    "unsure": "",
    "observation": "taken as something noticed",
}


def taken_as(kind: str) -> str:
    """What this console decided a message was, in words, or nothing when it decided the ordinary."""
    return _TAKEN_AS.get(kind, "")


def as_drawn_json(said: str, cards: Sequence[str]) -> str:
    """What a drawing block stores: the words, and the cards to put on the bench.

    The same shape a rearranging answer stores under, and for the same reason: a block has to be
    both readable by a person scrolling back and applicable by the page. `agent_desk/handling.py`
    argues it at length; this is the second thing that needed it, which is what makes the shape
    worth having rather than a one-off.
    """
    return json.dumps({"drawing": {"said": said, "cards": list(cards)}})


def as_will_run(said: str, cards: Sequence[str]) -> str:
    """What a block stores when a run was understood but not started.

    The same two-halves shape as a drawing and a rearrangement, and for the third time the same
    reason: a person scrolling back has to be able to read what happened, and the page has to be
    able to act on it. Kept apart from `as_drawn_json` because these cards are not being *put* on
    the bench — they are already there, and a page that treated the two alike would pin a card that
    somebody had taken off while the console was asking.
    """
    return json.dumps({"willrun": {"said": said, "cards": list(cards)}})


def read_will_run(said: str) -> tuple[str, list[str]]:
    """The words and the cards a waiting run would use, or nothing for any other block."""
    try:
        found = json.loads(said).get("willrun")
    except (ValueError, AttributeError):
        return "", []
    if not isinstance(found, dict):
        return "", []
    return str(found.get("said", "")), [str(one) for one in found.get("cards", [])]


def read_drawn(said: str) -> tuple[str, list[str]]:
    """The words and the card names back out, or nothing when a block stored something else."""
    try:
        found = json.loads(said).get("drawing")
    except (ValueError, AttributeError):
        return "", []
    if not isinstance(found, dict):
        return "", []
    return str(found.get("said", "")), [str(one) for one in found.get("cards", [])]


def as_drawn(steps: list[dict[str, str]], lines: list[dict[str, str]]) -> str:
    """A drawing a message produced, as the words its block shows.

    The steps as they will appear, so somebody can see whether it understood before they look at
    the bench — the same shape the "in words" panel offers, because a proposal read in two places
    that disagree is worse than one read in neither.
    """
    said = [f"{number}. {one['role']} — {one['label']}" for number, one in enumerate(steps, 1)]
    for one in lines:
        word = one["says"] or one["kind"]
        said.append(f"   {one['from']} → {one['to']} ({word})")
    return "\n".join(said)


def carried_by_kind(context: str) -> list[tuple[str, list[str]]]:
    """The lines a block recorded, gathered under the word each one begins with.

    Two dozen flat lines answer "what exactly" and not "what was this about", and the second is the
    question somebody opening a record a week later actually has. The largest one in this store is
    ninety-six lines long.

    The grouping is the lines' own first word — `idea · …`, `session · …`, `earlier · …` — rather
    than a vocabulary invented here. The console wrote those words when it wrote the line, and a
    second set of names for the same things would be a second answer to what a card is.

    A line with no `·` in it keeps its own place under an empty name, in the order it arrived: the
    lines `pasted.as_lines` writes and the note somebody typed on the workbench are sentences
    rather than cards, and folding them under a heading they do not have would file them as
    something they are not.
    """
    found: list[tuple[str, list[str]]] = []
    under: dict[str, list[str]] = {}
    for line in context.splitlines():
        kind, sep, said = line.partition(" · ")
        name = kind.strip() if sep else ""
        if name not in under:
            under[name] = []
            found.append((name, under[name]))
        under[name].append(said.strip() if sep else line)
    return found


def carried_shape(context: str) -> str:
    """How many of each, in one line, for the summary somebody reads before opening it."""
    counted = [(name, len(lines)) for name, lines in carried_by_kind(context) if name]
    return " · ".join(f"{name} {many}" for name, many in counted)
