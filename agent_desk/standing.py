"""Where the work stopped, in five hundred tokens.

*«Эта сессия сжималась дважды. Каждый раз я терял детали и заново выяснял, где нахожусь:
перечитывал пул, идею, код.»*

Everything here is already in the database — which idea was closed by which commit, what the gate
said, what has been spent. What was missing is one answer with all of it in it, short enough to be
the first thing read after a context window is compacted.

## Why it is short on purpose, and says what it left out

An answer that grows with the shift is an answer that stops being read on the day it matters most.
So there is a hard ceiling, and what did not fit is named as a number rather than dropped: a
reader who knows there are eleven more lines can ask for them, and a reader who does not know
believes they have the whole thing.

## What it will not say

It reports what this console wrote down itself and nothing else. It does not say whether the
working tree is clean, because nothing here has looked; it does not say a run is going because a
run has not finished. The fifth rule of CLAUDE.md is not suspended for a summary — a status guessed
here is worse than a gap, because this is precisely the text somebody reads instead of checking.
"""

from __future__ import annotations

from agent_desk.observe.model import now_ms, since
from agent_desk.store.repo import Store

# How much of this there may be. Five hundred tokens is roughly two thousand characters, and the
# number is the point of the whole thing rather than a limit that happens to apply.
MOST_CHARS = 2000

MORE = "… and {left} more line{s}. The whole shift is at /shift."

# How many lines of the shift itself are shown. The last things that happened are the ones that
# say where somebody is; the rest is history and has a route of its own.
LAST_LINES = 12


def within(said: str, *, most: int = MOST_CHARS) -> str:
    """Cut on a line boundary and say how many lines went.

    On a boundary because half a sentence about a commit is worse than no sentence: a reader cannot
    tell a truncated fact from a short one.
    """
    if len(said) <= most:
        return said
    lines = said.splitlines()
    kept: list[str] = []
    room = most - len(MORE.format(left=len(lines), s="s")) - 1
    for line in lines:
        if sum(len(one) + 1 for one in kept) + len(line) > room:
            break
        kept.append(line)
    left = len(lines) - len(kept)
    return "\n".join([*kept, MORE.format(left=left, s="" if left == 1 else "s")])


async def where_it_stopped(store: Store) -> str:
    """The one answer: what was being worked on, what was committed, what the gate said.

    Written as text rather than as a page because the reader is usually not a person with a
    browser — it is whatever starts next and has to find out where it is.
    """
    now = now_ms()
    shift = await store.the_shift()
    if shift is None:
        return "Nothing has happened yet. No idea has been closed and no commit has been recorded."

    steps = await store.shift_steps(shift.id)
    said = [
        f"The shift began {since(shift.began_at, now)} ago and has {len(steps)} "
        f"line{'' if len(steps) == 1 else 's'} in it.",
    ]

    spent = await store.spent_since(shift.began_at)
    # Said as a sentence rather than as a number on its own, because the number is only half of
    # what it means: it counts this console's own model calls and nothing an agent did.
    said.append(
        f"Model calls in it have cost ${spent:.2f}. What agents did in their worktrees is not "
        "measured — not zero, not measured."
    )

    open_ = [one for one in await store.ideas() if one.state in ("new", "kept", "promoted")]
    said.append(
        f"{len(open_)} idea{'' if len(open_) == 1 else 's'} "
        f"{'is' if len(open_) == 1 else 'are'} open."
        + (f" The newest is {open_[0].id}: {open_[0].summary}" if open_ else "")
    )

    commits = [one for one in reversed(steps) if one.what == "commit"]
    said.append(f"Last commit: {commits[0].said}" if commits else "No commit in this shift yet.")

    red = [one for one in reversed(steps) if one.what == "gate" and one.said.startswith("red")]
    green = [one for one in reversed(steps) if one.what == "gate" and one.said.startswith("green")]
    if red and (not green or red[0].at > green[0].at):
        said.append(f"The gate was last red: {red[0].said[4:].strip()}")
    elif green:
        said.append("The gate was last green.")
    else:
        said.append("The gate has not reported in this shift.")

    said.append("")
    said.append("What happened, most recent last:")
    said += [f"  {since(one.at, now)} ago · {one.what} · {one.said}" for one in steps[-LAST_LINES:]]
    return within("\n".join(said))
