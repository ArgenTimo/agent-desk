"""What a card is in a process: Object, Action, Decision, Event, Result.

From the first user's feedback, and it is the vocabulary everything else in that feedback rests
on: *"нам нужно несколько типов карточек на доске — Object (что-то существует), Action (что-то
сделать), Decision (выбрать / проверить условие), Event (что-то произошло), Result (что-то
получилось)"*.

Five, and the number matters more than it looks. It is the same five that every process notation
converges on because they are the distinctions you cannot describe work without: a thing, a step,
a fork, a trigger, an outcome. Six would be a taxonomy somebody has to learn; four leaves you
unable to say when something starts.

## Why a role is not a kind

A card's `kind` — session, idea, blocker, folder — says **where it is read from**, and it cannot
change: an idea does not become a session. Its role says **what it is doing in the process being
described**, and it changes as the description does — *"карточка может менять тип по ходу
процесса"*. One field cannot carry both, and the version of this that reused `kind` would have
made "this idea is the Result of that step" a thing you could not say.

## Why absent is a real answer

Almost every card on a bench has never been typed by hand, and asking somebody to type five cards
before they can draw one line is how a constructor goes unused. So every kind has a role it
naturally is, and a stored role is somebody having said otherwise — which is exactly the shape of
the existing rule about state: a default that reads like a judgement is a guess (CLAUDE.md,
rule five). The defaults below are readings of what each kind already is, not predictions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    """One of the five, and the words for it on a card."""

    name: str
    says: str
    means: str
    # A shape somebody reads before they read the text, which is the whole argument for having
    # five names rather than a free-text label: "ромб читается как решение до того, как прочитан
    # текст внутри". The stylesheet draws these; this is where the list of them lives.
    shape: str


ROLES: dict[str, Role] = {
    "object": Role("object", "Object", "something that exists", "box"),
    "action": Role("action", "Action", "something to do", "bar"),
    "decision": Role("decision", "Decision", "choose, or check a condition", "corner"),
    "event": Role("event", "Event", "something happened", "round"),
    "result": Role("result", "Result", "something came out", "double"),
}

# What each kind of card already is, before anybody says otherwise.
#
# Read these as answers to "if this were a step in a process, which of the five would it be" —
# a session is work happening, a blocker is a thing that occurred, an idea is a thing that exists
# and has not been done. A collection is the one that is obviously a Result: it is what a question
# produced.
NATURALLY = {
    "session": "action",
    "agent": "action",
    "task": "action",
    "blocker": "event",
    "idea": "object",
    "project": "object",
    "instance": "object",
    "folder": "object",
    "file": "object",
    "connector": "object",
    "note": "object",
    "block": "event",
    "group": "result",
}

# What a card with no kind this program recognises is. `object` rather than nothing: a card on the
# bench is at least a thing that exists, and refusing to type it would leave a hole in a diagram
# whose whole value is that every box says what it is.
OTHERWISE = "object"


def role_of(kind: str, chosen: str = "") -> Role:
    """The role this card has: the one somebody chose, or the one its kind already is.

    A `chosen` value this program does not have is treated as absent rather than as an error.
    Roles are written by a page and read here; a name that has since been removed from the five
    should render as the card's natural role, not as a crash on somebody's board.
    """
    if chosen in ROLES:
        return ROLES[chosen]
    return ROLES[NATURALLY.get(kind, OTHERWISE)]


def is_a_role(name: str) -> bool:
    """Whether this is one of the five. The route's whole validation."""
    return name in ROLES
