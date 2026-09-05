"""A transcript of a meeting that already happened, read into ideas (docs/10-meeting-intake.md §1+).

The first of the three versions that page describes, and the only one that needs nothing this
machine does not have: no audio, no consent from a room, no turn granted by a human. Somebody
pastes what was said and the pool gains what was decided in it.

Two things this is careful about, and both are the same rule the typed inbox already follows.

**It proposes; it does not decide.** Everything it finds arrives as an ordinary idea in the `new`
state, marked as having come from a meeting, and a person keeps or discards each one exactly as
they would a thought they typed. A transcript is full of things that were said and not meant —
half-sentences, options nobody chose, somebody thinking aloud — and a tool that filed those as
decisions would have made the pool less trustworthy rather than more full.

**It never invents.** The same instruction the splitter carries, for the same reason: a line in
the pool that nobody said is indistinguishable a week later from a line somebody did.

A meeting is longer than a message, so it is read in passes rather than in one gulp — a transcript
does not fit in one useful prompt, and a single answer over forty minutes of talk returns four
bland lines. Each pass is bounded and its ideas are captured before the next one runs, so an
interrupted read leaves what it already found.
"""

from __future__ import annotations

import structlog

from agent_desk.answer.session import AnswerFailed, stream_answer
from agent_desk.ideas import inbox, kin
from agent_desk.store.repo import Idea, Store

log = structlog.get_logger()

# How much of a transcript one pass reads. Characters rather than lines: a transcript is one
# speaker per line and the lines vary from a word to a paragraph.
CHUNK_CHARS = 6000
# And how many passes at most, so a transcript somebody pasted twice by accident cannot run all
# night. Forty minutes of talk is comfortably inside this.
MOST_PASSES = 12
# What one pass may find. The same bound as the splitter's, and for the same reason: more than
# this from one stretch of talk is a summary, not a set of ideas.
MOST_PER_PASS = 6


def read_prompt(part: str) -> str:
    """Ask for what was *decided or wanted*, and nothing else that was said."""
    return "\n".join(
        [
            "Below is part of a transcript of a meeting between people working on software.",
            "",
            "Write down the ideas in it: things somebody said should exist, should change, or is",
            "wrong today. One per line, in their words, each a line that stands on its own.",
            "",
            "Rules, and the first is the one that matters:",
            "- **Never invent one.** If this part of the transcript contains no idea, reply with",
            "  the single word `none`. That is a normal answer and most parts of most meetings",
            "  deserve it.",
            "- Not everything said is an idea. Skip greetings, status, questions that were",
            "  answered, options somebody raised and the room rejected, and thinking aloud.",
            "- Do not merge two ideas into one line, and do not split one across two.",
            f"- At most {MOST_PER_PASS} lines. No numbering, no bullets, no preamble.",
            "",
            part,
        ]
    )


def read_ideas(reply: str) -> list[str]:
    """The lines the reply names. `none`, and anything unusable, is nothing.

    The opposite default from the splitter's, and deliberately: there, unparsed text was one idea
    somebody definitely typed, and losing it was the only failure. Here, unparsed text is a model's
    reading of a room, and inventing from it is the only failure.
    """
    lines = [
        stripped.lstrip("-*•0123456789.) ").strip()
        for line in reply.splitlines()
        if (stripped := line.strip())
    ]
    lines = [line for line in lines if line and line.lower() not in ("none", "none.")]
    return lines[:MOST_PER_PASS]


def parts(transcript: str) -> list[str]:
    """The transcript in readable stretches, split on line breaks rather than mid-sentence."""
    lines = transcript.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) > CHUNK_CHARS and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks[:MOST_PASSES]


async def read_meeting(
    store: Store, transcript: str, *, project_key: str | None = None
) -> list[Idea]:
    """Read one transcript into the pool. Returns what it wrote down.

    Each pass is captured before the next one runs, so an interrupted read leaves what it already
    found — and every idea goes through the same placement as a typed one, so a meeting that
    repeats last week's decision does not fill the pool with it again (`ideas/kin.py`).
    """
    written: list[Idea] = []
    for part in parts(transcript):
        try:
            reply = "".join([chunk async for chunk in stream_answer(read_prompt(part))])
        except (AnswerFailed, OSError):
            # What was found so far is kept. A meeting half-read is a meeting half-read, and it is
            # better than losing the part that worked.
            log.warning("meeting.read_failed", found=len(written))
            break
        for said in read_ideas(reply):
            idea = await inbox.capture(
                store,
                said,
                source_kind="meeting",
                context={"from": "a meeting transcript"},
                project_key=project_key,
            )
            await kin.place(store, idea)
            written.append(idea)
    log.info("meeting.read", ideas=len(written))
    return written
