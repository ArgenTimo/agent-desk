"""A background pass that reads the pool, and the two things it is allowed to say about an idea.

Asked for as "фоновый процесс анализа идей по различным критериям" and "подсветка идей
специальными цветами по результатам анализа". A list of sixty thoughts is a list nobody reads, and
what makes it unreadable is that every row looks equally like every other — a two-line fix and a
month of work in the same font, on the same card, in the same colour.

So: two questions, asked once per idea, and both about the *text* rather than about the world.

**How big is it** — `small`, `medium`, `large`. A reading of what was written, not an estimate:
nobody is going to plan against this, and the value is entirely in a list where the two-line fixes
are visible as two-line fixes.

**What it needs next** — `ready` when somebody could start on it as written, `decide` when it
cannot be started until a person chooses something, and `built` when it reads like a description
of something that already exists.

Three rules, and they are the same three every model call in this repository follows.

**It never writes `state`.** That column is the human's: `new`, `kept`, `promoted`, `dropped`,
`done` are what a person decided. This pass writes two columns of its own next to it, and the card
renders them as a reading rather than as a fact — `built` in particular is offered as a question
with a button, never as a state, because "this is already built" is exactly the claim CLAUDE.md's
fifth rule says not to make from an inference.

**It never hides anything.** No filter, no auto-drop, no reordering that buries a row. A colour
and a word, and everything stays in the list.

**It is allowed to fail.** An unavailable model leaves `appraised_at` null, which renders as
nothing at all — which is what an unread idea should look like.
"""

from __future__ import annotations

import re

import structlog

from agent_desk.answer.session import AnswerFailed, stream_answer
from agent_desk.store.repo import Idea, Store

log = structlog.get_logger()

# How many are read in one pass. One model call each, so a sweep that took sixty in a tick would
# be a sweep that hurts on the day somebody pastes a meeting into the box.
AT_A_TIME = 3

SIZES = ("small", "medium", "large")
SHAPES = ("ready", "decide", "built")

# What each answer means on a card, in words somebody who does not write code would use.
SAYS: dict[str, str] = {
    "small": "small",
    "medium": "a few days",
    "large": "big",
    "ready": "ready to start",
    "decide": "needs you to decide something",
    "built": "may already be built",
}

_ANSWER = re.compile(r"\A(small|medium|large)\s+(ready|decide|built)\Z", re.IGNORECASE)


def appraise_prompt(idea: Idea) -> str:
    return "\n".join(
        [
            "Read one idea from a developer's notebook and answer with exactly two words on one",
            "line, separated by a space, and nothing else.",
            "",
            "The first word is how much work it looks like:",
            "- `small` — an afternoon or less.",
            "- `medium` — a few days.",
            "- `large` — more than that, or too vague to be less.",
            "",
            "The second word is what it needs next:",
            "- `ready` — somebody could start on this as written.",
            "- `decide` — it cannot be started until a person chooses something first.",
            "- `built` — it reads like a description of something that already exists.",
            "",
            "Answer `medium ready` if you are unsure. Do not explain.",
            "",
            "## The idea",
            idea.text,
        ]
    )


def read_appraisal(reply: str) -> tuple[str, str]:
    """The two words, or the safe pair. Anything unparsable is `medium ready`, which is the
    reading that changes nothing about how the card looks."""
    first = next((line.strip() for line in reply.splitlines() if line.strip()), "")
    found = _ANSWER.match(first.rstrip("."))
    if found is None:
        return "medium", "ready"
    return found.group(1).lower(), found.group(2).lower()


async def appraise(idea: Idea) -> tuple[str, str] | None:
    """What this idea looks like, or `None` when nothing could be asked."""
    try:
        reply = "".join([chunk async for chunk in stream_answer(appraise_prompt(idea))])
    except (AnswerFailed, OSError):
        return None
    return read_appraisal(reply)


async def already_there(store: Store, idea: Idea) -> str:
    """Evidence that this idea is already built, or an empty string. Facts, not a reading.

    "Сервис сам определяет, исполнена ли идея и зарегистрирована ли она как фича" — and the whole
    difference between this and the `built` the sweep can guess at is where the answer comes from.
    The sweep reads the idea's own words and says "this looks like something that exists", which
    is a hunch. This looks at what the console actually did:

    - a ticket filed for it (docs/adr/0005), which is the strongest evidence there is: somebody
      pressed the button and a tracker answered with a key;
    - a task queued or finished that names it, which means work was started on it here.

    What it deliberately does *not* do is search the repository. "There is a function with a
    similar name" is not evidence that somebody's idea was built, and a check that says so would
    be worse than no check — it is the guess this exists to replace, wearing a grep.
    """
    filing = await store.filing_of(idea.id)
    if filing is not None:
        return f"filed as {filing.issue_key}"

    for task in await store.tasks(limit=500):
        if idea.id not in (task.source_ref or ""):
            continue
        if task.finished_at:
            return f"an agent worked on it and finished ({task.title[:60]})"
        return f"an agent is working on it ({task.title[:60]})"
    return ""


async def sweep(store: Store) -> int:
    """Read the ideas nobody has read yet. Returns how many were looked at.

    Never raises: this is called from a loop, and a loop that dies takes the console with it.
    """
    looked = 0
    for idea in await store.unappraised_ideas(AT_A_TIME):
        # Evidence first, because it is free and it is a fact. Only where there is none does a
        # reading of the text get a say.
        evidence = await already_there(store, idea)
        if evidence:
            await store.appraise_idea(idea.id, size="small", shape="built")
            await store.say_card(f"idea:{idea.id}", f"already built — {evidence}", idea.text[:400])
            log.info("ideas.already_built", idea=idea.id, evidence=evidence)
            looked += 1
            continue
        made_of_it = await appraise(idea)
        if made_of_it is None:
            # Left unread rather than marked with a guess: an unread idea should look unread.
            break
        size, shape = made_of_it
        await store.appraise_idea(idea.id, size=size, shape=shape)
        log.info("ideas.appraised", idea=idea.id, size=size, shape=shape)
        looked += 1
    return looked
