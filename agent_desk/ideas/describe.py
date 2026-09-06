"""A sentence about one thing on the board, for the middle view of its card.

"Метадата — созданное ЛЛМ описание элемента, например что представляет из себя проект или чем
занята сессия."

The board is already good at saying what it *reads*: a status the session wrote about itself, a
branch, the last line of a transcript, a token count. What it cannot do is say what a thing **is**
— "the console's own repository, being rewritten around a single workbench" — in a sentence
somebody who has not read the code would understand. That is a different job and it needs a model.

Three rules, and they are the ones every model call in this repository follows.

**It is never in the way.** A card renders whether or not a description exists. The board does not
wait for one, and a description that has not been written yet is simply absent — which reads as an
ordinary card rather than as a hole.

**It is written once.** A board of twenty cards would otherwise be twenty model calls every two
seconds. What it was written *from* is kept beside it, so it is rewritten when that changes
materially and left alone when it has not — otherwise a session's description would be about
whatever it happened to be doing the first time somebody looked at it.

**It describes; it does not judge.** No priorities, no advice, no "this looks stuck". The board has
its own words for those, they are checked, and a model's opinion next to them would be indistinguishable
from a fact (CLAUDE.md, rule five).
"""

from __future__ import annotations

import difflib

import structlog

from agent_desk.answer.session import AnswerFailed, stream_answer
from agent_desk.store.repo import Store

log = structlog.get_logger()

# How many are written in one pass. Each is a model call, and a board that has just been opened
# should not spend twenty of them at once.
AT_A_TIME = 4

# How alike what we knew and what we know now has to be for the old sentence to stand. A session's
# last line changes constantly, and rewriting the description every time would be a model call
# every few seconds saying almost the same thing.
#
# A ratio rather than a character count, because a character count means something different for a
# two-line project card and a ten-line session card — and this number has to be explainable to
# whoever next wonders why a card's description is out of date.
STILL_THE_SAME = 0.75


def describe_prompt(kind: str, about: str) -> str:
    """Ask for one sentence about what this is, in plain words."""
    return "\n".join(
        [
            f"Below is what a console knows about one {kind} it is watching.",
            "",
            "Write one sentence saying what it is and what it is for, in plain words somebody who",
            "does not write code would understand. Reply with the sentence and nothing else.",
            "",
            "Rules:",
            "- At most 25 words.",
            "- Describe; do not judge. No priorities, no advice, no guessing whether it is stuck",
            "  or going well — the console has its own checked words for that.",
            "- Do not invent anything that is not below. If there is too little to say, reply with",
            "  the single word `nothing`.",
            "",
            about,
        ]
    )


def read_description(reply: str) -> str:
    """The sentence, or nothing. `nothing` is a normal answer for a card with nothing to say."""
    first = next((line.strip() for line in reply.splitlines() if line.strip()), "")
    if not first or first.lower().rstrip(".") == "nothing":
        return ""
    return first[:300]


def changed_enough(before: str, now: str) -> bool:
    """Is what we know different enough to be worth another model call?"""
    if not before:
        return True
    if before == now:
        return False
    return difflib.SequenceMatcher(None, before, now).ratio() < STILL_THE_SAME


async def describe(store: Store, name: str, kind: str, about: str) -> str:
    """The sentence for this card, writing it if there is not one yet. Never raises.

    Returns the empty string when there is nothing written and nothing could be written, which the
    card renders as no line at all.
    """
    said, written_from = await store.card_said(name)
    if said and not changed_enough(written_from, about):
        return said
    if not about.strip():
        return said

    try:
        reply = "".join([chunk async for chunk in stream_answer(describe_prompt(kind, about))])
    except (AnswerFailed, OSError):
        # The old one still stands, and no sentence at all is an ordinary card.
        return said

    fresh = read_description(reply)
    if not fresh:
        return said
    await store.say_card(name, fresh, about)
    log.info("cards.described", card=name)
    return fresh
