"""New thread, or continuation of an open one.

docs/04-threads-and-blocks.md: a thread is a subject, and attaching a follow-up to its subject is
what makes "and what about the other one" work — the block inherits the thread's context.

**This module assumes it is wrong sometimes.** It is a small model call on short text with no
ground truth, and the failure is annoying in both directions: a follow-up stranded in its own
thread loses its context, a new subject swallowed into an old one gets answered against the wrong
background. So every decision it makes is visible on the block and reversible in one click, and
every reversal is logged — the correction rate is the number that decides whether this module
should exist at all (docs/09-roadmap.md).

Three rules hold it in place:

- **New is the safe answer**, and it is what a failure produces. Attaching wrongly is the more
  expensive mistake, because it silently changes what a question is answered against.
- **Nothing is merged automatically.** Two subjects that turn out to be one is a judgement, and
  the human makes it.
- **`/new` never reaches here.** When you already know, you should not have to hope.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from agent_desk.answer.session import AnswerFailed, stream_answer
from agent_desk.store.repo import Thread

# The reply is one token, and it is read as one token. Searching the whole reply for a digit was
# worse than useless: "This mentions 2 different files, so: new" attached the block to thread two,
# and so did "Error: rate limited after 2 retries" — the model said new, twice, and was overruled
# by its own prose. Attaching wrongly is the expensive mistake, so anything that is not exactly a
# choice is a new subject.
# `[0-9]` rather than `\d`, which in Python also matches Arabic-Indic and other Unicode digits —
# `int()` accepts those, so `١` would have selected thread one.
_CHOICE = re.compile(r"\A([0-9]{1,2}|new)\Z", re.IGNORECASE)


def prompt(text: str, threads: Sequence[Thread]) -> str:
    lines = [
        "A developer typed one line into a console that watches their Claude Code sessions.",
        "Decide whether it continues one of the open subjects below, or starts a new one.",
        "",
        "Answer with the number of the subject it continues, or the word new. One token, nothing",
        "else. When it is not clearly a continuation, answer new: attaching a question to the",
        "wrong subject changes what it gets answered against, and that is the worse mistake.",
        "",
        "## Open subjects",
    ]
    lines += [f"{index}. {thread.subject}" for index, thread in enumerate(threads, start=1)]
    lines += ["", "## The line", text]
    return "\n".join(lines)


def read_choice(reply: str, threads: Sequence[Thread]) -> str | None:
    """The thread id the reply names, or `None` for a new subject.

    Only the first token is read, and it must be the whole answer once trailing punctuation is
    off it. A reply that says anything else — a sentence, an apology, an error, a number inside a
    sentence — is a decision this module did not understand, and an unparsed decision is a new
    thread rather than a guess at what the model meant.
    """
    words = reply.strip().split()
    if len(words) != 1:
        # One token, and the whole reply. "2 files mention this, so it is new" begins with a digit
        # and ends with the model's actual answer; reading only the first word overruled it just
        # as thoroughly as searching the whole text did.
        return None
    match = _CHOICE.match(words[0].strip(".,:;!?\"'"))
    if match is None or match.group(1).lower() == "new":
        return None
    index = int(match.group(1))
    if 1 <= index <= len(threads):
        return threads[index - 1].id
    return None


async def classify(text: str, threads: Sequence[Thread]) -> str | None:
    """Which open thread this belongs to, or `None`.

    Never raises. A classifier that could fail a submission would be a classifier that makes the
    input field unreliable to keep the threading tidy, which is the wrong trade in a tool whose
    first promise is that typing costs nothing.
    """
    if not threads:
        return None
    try:
        reply = "".join([chunk async for chunk in stream_answer(prompt(text, threads))])
    except (AnswerFailed, OSError):
        return None
    return read_choice(reply, threads)
