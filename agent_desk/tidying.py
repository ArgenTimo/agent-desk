"""Whether a session whose canary is lost may be closed.

*«Закрытие сессии выбрасывает то, что она не закоммитила. Это единственное необратимое действие во
всей консоли, и решение о нём должно приниматься с открытыми глазами.»*

The decision, and what the alternatives would have cost, is `docs/adr/0012`.

So this module is the eyes. It decides nothing about *whether* a project wants this — that is a
switch somebody pressed — and everything about whether this particular session may go.

## Four conditions, and the answer says which one failed

A caller that is told "no" and not why has to go and work it out, and the place it would go is a
session it was about to close. So the answer carries the reason, and the console shows it on the
card: "it still has uncommitted work" is a sentence somebody can act on; a button that quietly did
nothing is not.

## Why idle, and why idle for a while

«Сначала дать доработать и закоммитить, только потом закрывать.» A session mid-turn has something
in flight. A session that went idle four seconds ago may be between two turns of the same piece of
work, and the status field cannot tell those apart — so the wait is real time, long enough that
somebody who was going to commit has.

Pure: it is given what was read and answers. Reading `git status` is the caller's, because reading
a disk is a thread and this is a decision.
"""

from __future__ import annotations

from dataclasses import dataclass

# How long a session has to have been idle. Long enough that "let it finish what it is on and
# commit" is time somebody had, short enough that a console left running overnight tidies up.
QUIET_FOR_MS = 30 * 60 * 1000


@dataclass(frozen=True)
class Maybe:
    """Whether this one may be closed, and why not when it may not."""

    yes: bool
    why: str = ""


def may_close(
    *,
    armed: bool,
    canary_lost: bool,
    status: str,
    clean: bool,
    idle_for_ms: int,
) -> Maybe:
    """Whether this session may be closed now.

    Every condition is stated rather than inferred, and the order is the order somebody would check
    them in: is this even switched on, is anything wrong with the session, is any work at risk, and
    has it been left alone long enough.
    """
    if not armed:
        return Maybe(False, "this project has not been switched on for it")
    if not canary_lost:
        return Maybe(False, "it is still signing, so there is nothing to tidy")
    if status != "idle":
        # Not "busy" and not "shell": both mean something is in flight, and the third state this
        # can be in is a status the registry does not have (CLAUDE.md, rule five).
        return Maybe(False, f"it is {status}, and something in flight is not something to close")
    if not clean:
        return Maybe(False, "it still has uncommitted work in its checkout")
    if idle_for_ms < QUIET_FOR_MS:
        left = (QUIET_FOR_MS - idle_for_ms) // 60_000
        return Maybe(
            False, f"it went quiet recently — {left} more minute{'' if left == 1 else 's'}"
        )
    return Maybe(True, "its canary is lost, it is idle, and its checkout is clean")
