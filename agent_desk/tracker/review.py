"""Eleven comments in a review column are usually three problems (docs/adr/0011).

Asked for as: "пройди по таблице Jira, собери из комментариев к задачам в колонке In Review все
упомянутые блокеры. Сгруппируй их семантически в укрупнённые задачи для человека и к каждой напиши
короткий туториал — что конкретно нужно сделать, чтобы разблокировать."

`jira.read_review` does the reading and produces quotations: a sentence somebody wrote, and the
key of the ticket it was written on. Everything in *this* module is the other half — a judgement
that two sentences are about the same thing, and a paragraph about what to do — and the three
rules it follows are the ones every model call in this repository follows.

**It never invents a source.** The model is shown the mentions and answers with ticket keys; a key
that was not in what it was shown is dropped, and a group left with none is dropped whole. The
quotations on the card are then rebuilt from `read_review`'s own mentions rather than from the
reply, so the words under a group are always words a person actually wrote (CLAUDE.md, rule five).

**It says whose sentence each half is.** The title and the tutorial are a model's writing and the
card labels them as one; the quotes beneath them are the board's. A synthesis that renders like a
quotation is the guessed status the fifth rule is about, wearing better prose.

**It is allowed to fail, and failing changes nothing.** An unreadable board and an unavailable
model both leave the rows exactly as they were, because the alternative — clearing them — makes a
column nobody could read look like a column with nothing in it. Only a board that was read and
genuinely says nothing clears anything.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from agent_desk.answer.session import AnswerFailed, stream_answer
from agent_desk.store.repo import Store
from agent_desk.tracker import jira

log = structlog.get_logger()

# How many sentences one judgement is shown. Past this the model's attention is the bottleneck
# rather than its judgement, and a review column with forty blocker sentences on it has a problem
# no console is going to summarise away.
MOST_MENTIONS = 40

# How many groups one pass may produce. "Укрупнённые задачи для человека" is the whole point: a
# column of eleven grouped into eleven is the list somebody already had.
MOST_GROUPS = 8

_TITLE = re.compile(r"\A#{1,6}\s*(.+?)\s*\Z")
_TICKETS = re.compile(r"\Atickets?\s*:\s*(.+)\Z", re.IGNORECASE)
_KEY = re.compile(r"\b[A-Z][A-Z0-9_]{1,19}-\d+\b")
_STEP = re.compile(r"\A(?:[-*]|\d+[.)])\s*(.+?)\s*\Z")


@dataclass(frozen=True)
class Holdup:
    """One thing several tickets are waiting on, and what a person would do about it."""

    # A slug of the title, so a pass that groups the same comments the same way produces the same
    # card — and the card keeps whatever somebody claimed about it (029-blocker-checking.sql).
    id: str
    title: str
    tutorial: str
    # The sentences it was made from, one per line, each with the key of the ticket it was written
    # on. The evidence, and the only part of a card here that is not a judgement.
    said: str
    keys: tuple[str, ...] = ()


def slug(title: str) -> str:
    """A short stable name for a title. Empty when there is nothing in it to name."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]


def group_prompt(mentions: Sequence[jira.Mention]) -> str:
    """Ask for larger problems and the steps to clear them, and make invention hard.

    The shape is fixed and dull on purpose: a reply this parses wrongly is a card claiming a
    ticket said something it did not, and there is no way to see that from the console.
    """
    lines = [
        "Below are sentences from comments on tickets sitting in a review column. Each was",
        "written by a person and says something is waiting, stuck or blocked. They repeat each",
        "other: eleven comments are usually three problems.",
        "",
        f"Group them into at most {MOST_GROUPS} problems. For each, write what a person has to do",
        "to clear it.",
        "",
        "Answer with nothing but groups, in exactly this shape:",
        "",
        "## the problem, as one thing a person can do, under 80 characters",
        "tickets: ABC-1, ABC-4",
        "1. a step: one action, specific enough to start on",
        "2. the next step",
        "",
        "Rules:",
        "",
        "- Use only the ticket keys listed below. Do not invent one, and do not write a key that",
        "  is not in the list — a group whose keys are all invented is thrown away.",
        "- Every step is something a person does: a command to run, a page to open, a person to",
        "  ask, a decision to take. Never `investigate` or `look into it`.",
        "- Two sentences about different things are two groups. Filing two problems as one hides",
        "  one of them from the person who has to fix it.",
        "- Write nothing outside the groups: no preamble, no closing sentence.",
        "",
        "## The sentences",
    ]
    lines += [f"- {one.key} ({one.summary}): {one.said}" for one in mentions[:MOST_MENTIONS]]
    return "\n".join(lines)


def read_groups(reply: str, mentions: Sequence[jira.Mention]) -> tuple[Holdup, ...]:
    """The groups in one reply, with every claim about a source checked against the mentions.

    Anything unparsable yields nothing rather than a half-read group: a card here says a person
    wrote a sentence, and that has to be true or the column is worse than empty.
    """
    known = {one.key for one in mentions}
    said_of = {
        key: [f"{one.key} · {one.said}" for one in mentions if one.key == key] for key in known
    }

    found: list[Holdup] = []
    title = ""
    keys: list[str] = []
    steps: list[str] = []

    def close() -> None:
        # A group needs all three: a title, a ticket that is really in the column, and something
        # to do. Missing any one of them, it is not a card anybody can act on.
        wanted = [key for key in dict.fromkeys(keys) if key in known]
        if not title or not wanted or not steps or not slug(title):
            return
        quotes = [line for key in wanted for line in said_of[key]]
        found.append(
            Holdup(
                id=slug(title),
                title=title[:200],
                tutorial="\n".join(steps)[:1500],
                said="\n".join(quotes)[:1500],
                keys=tuple(wanted),
            )
        )

    for raw in reply.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = _TITLE.match(line)
        if heading is not None:
            close()
            title, keys, steps = heading.group(1), [], []
            continue
        if not title:
            # Anything before the first heading is the preamble the prompt asked for and did not
            # get. It names no group, so it belongs to none.
            continue
        tickets = _TICKETS.match(line)
        if tickets is not None:
            keys += _KEY.findall(tickets.group(1))
            continue
        step = _STEP.match(line)
        steps.append(step.group(1) if step is not None else line)
    close()

    # Two groups the model named the same way are one card, and the second would collide with the
    # first on its own primary key.
    seen: dict[str, Holdup] = {}
    for one in found[:MOST_GROUPS]:
        seen.setdefault(one.id, one)
    return tuple(seen.values())


async def group(mentions: Sequence[jira.Mention]) -> tuple[Holdup, ...] | None:
    """The problems behind these sentences, or `None` when nothing could be asked.

    `None` and `()` are different answers and the caller depends on it: the first means this pass
    knows nothing and must not overwrite what an earlier one knew, the second means it asked and
    the reply held no group anybody could act on.
    """
    try:
        reply = "".join([chunk async for chunk in stream_answer(group_prompt(mentions))])
    except (AnswerFailed, OSError):
        return None
    made = read_groups(reply, mentions)
    return made or None


async def _destinations(store: Store) -> list[tuple[str, jira.Destination]]:
    """Every project with a board this console has been given a link and a credential for.

    Every project, rather than every *armed* one: reading a board is free and changes nothing in
    it (docs/adr/0010), and a blocker somebody has to clear is worth showing whether or not this
    console is also starting work on that project.
    """
    found: dict[str, jira.Destination] = {}
    for link in await store.links():
        where = jira.destination_of(link.url, link.token_env)
        if where is not None:
            found.setdefault(link.repo_key, where)
    return list(found.items())


async def sweep(store: Store) -> int:
    """Read every board's review column and write down what it is waiting on. Returns how many.

    Never raises: this is called from a loop, and a loop that dies takes the console with it.
    """
    made = 0
    for repo_key, where in await _destinations(store):
        read = await asyncio.to_thread(jira.read_review, where)
        if not read.ok:
            # Unread, which is not the same as empty. Nothing is replaced (docs/adr/0010).
            log.info("review.unread", repo=repo_key, detail=read.detail)
            continue
        if not read.mentions:
            # Read, and the column says nothing is stuck. This is the one case that clears rows,
            # and it has to: a comment somebody answered should stop being a blocker without
            # anybody telling this console.
            await store.replace_review_blockers(repo_key, ())
            continue
        holdups = await group(read.mentions)
        if holdups is None:
            log.info("review.ungrouped", repo=repo_key, mentions=len(read.mentions))
            continue
        await store.replace_review_blockers(
            repo_key, [(one.id, one.title, one.tutorial, one.said) for one in holdups]
        )
        log.info("review.grouped", repo=repo_key, groups=len(holdups), mentions=len(read.mentions))
        made += len(holdups)
    return made
