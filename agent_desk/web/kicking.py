"""The loop that will not let a session sit idle (docs/adr/0009).

The third loop in this program and the one that argues with the oldest rule in it. docs/adr/0002
says never write into a running session's context without an explicit human click, and it was
right about the half that survives: a message into a session that is *working* displaces the work.
It is not right about a session that finished its turn at three in the morning and sits at its
prompt until somebody notices — displacing nothing costs nothing, and those hours were paid for.

So what this module may do is narrow and each bound is a test:

- only a session somebody switched on, on that session's own card;
- only while the registry says `idle`, which is a fact the session writes about itself
  (docs/03-session-observation.md) — `busy` is never kicked, for any reason;
- only a background session, because `stop` + `--bg --resume` is a documented door and an
  interactive terminal has none this program is allowed to open;
- never with work it invented: either the task it was dispatched for, or the instruction
  docs/adr/0008 already wrote and already fenced;
- at most a stated number of turns an hour, and two failures in a row switch it off;
- and a rate limit is a wait rather than a failure — the switch stays on and the console records
  when to look again.

It lives under `web/` for the same reason the others do: it dispatches, and dispatching is a door
only `web/` may open (docs/adr/0006).
"""

from __future__ import annotations

import asyncio
import contextlib
import time

import structlog

from agent_desk import dispatch
from agent_desk.observe import registry
from agent_desk.observe.model import Session
from agent_desk.observe.shape import repository_of
from agent_desk.store.repo import Kicking, Store

log = structlog.get_logger()

# How often idle sessions are looked at. The same deliberate slowness as the queue's loop: a
# session that has been idle for thirty seconds is not more urgent than one that has been idle for
# ten, and a tick that costs a registry read is a tick worth spacing out.
TICK_SECONDS = 30.0

WINDOW_MS = 60 * 60 * 1000

# The same two-in-a-row rule the other loops use. A switch that keeps firing into a broken
# condition is the three-in-the-morning failure in its most ordinary form.
FAILURES_BEFORE_DISARM = 2

# How long to wait when the CLI says the account is out of budget but does not say until when.
# Long on purpose: guessing short means retrying into the same wall every few minutes, and the
# cost of waiting too long is one idle hour on a switch whose whole subject is idle hours.
DEFAULT_LIMIT_WAIT_MS = 30 * 60 * 1000

# The kinds of session this console can address. `bg` is what `claude --bg` writes; an interactive
# terminal is left alone and the card says why (docs/adr/0009).
KICKABLE_KINDS = ("bg", "background")


def kickable(session: Session) -> str:
    """Why this session cannot be kicked, or an empty string.

    A sentence rather than a boolean, because the card shows it: a disabled button with no reason
    next to it is the thing that makes somebody click it twice and then file a bug.
    """
    if session.kind not in KICKABLE_KINDS:
        return "only a background session can be continued from here"
    if session.status != "idle":
        return f"it is {session.status}, and a session that is working is never interrupted"
    return ""


def _repo_key(session: Session) -> str:
    """The key a project's standing note is filed under, from the directory the session is in.

    The same shape the board keys projects by, so a note written on a project's page reaches the
    sessions inside it — including the ones running in a worktree of that checkout.
    """
    return repository_of(session.cwd).key


def _sessions() -> dict[str, Session]:
    """Every live session, by the short id everything else in this program keys on."""
    return {
        session.session_id.split("-")[0]: session for session in registry.read_registry().sessions
    }


def why_not_kick(arming: Kicking, session: Session | None, now_ms: int, spent: int) -> str:
    """The one place that decides whether a kick may happen, so the card and the loop agree."""
    if not arming.armed:
        return "not switched on"
    if arming.waiting(now_ms):
        left = max(0, (arming.resume_at or 0) - now_ms) // 60_000
        return f"the account is out of budget for another {left} minutes"
    if spent >= arming.per_hour:
        return f"the hour's budget is spent ({spent} of {arming.per_hour})"
    if session is None:
        # Not an error and not a failure: a session that has exited has nothing left to continue,
        # and saying so is better than guessing that it is idle.
        return "that session is not running any more"
    return kickable(session)


def _spent(arming: Kicking, now_ms: int) -> int:
    """A budget this program can count without a second table: the last kick and the count.

    Deliberately crude. What the budget is protecting against is a burst — a loop that continues
    the same session forty times in a minute — and the last kick's timestamp is enough to stop
    that. It resets on the hour rather than sliding, which is the simpler thing that works.
    """
    if arming.kicked_at is None or now_ms - arming.kicked_at >= WINDOW_MS:
        return 0
    return arming.kicks


def carry_on(arming: Kicking, session: Session, standing: str = "") -> str:
    """What to say to a session that has stopped. Two prompts, and there is no third.

    It never invents the work. Either the session carries on with what it was doing — which it
    knows and this program does not, because the conversation is still there and `--resume` keeps
    it — or, if it has nothing outstanding, it gets the instruction docs/adr/0008 already wrote:
    find one thing that is broken, fix it, prove it, stop.

    Every kicked turn says who sent it. A transcript somebody reads in a month has to show which
    turns a person asked for and which a console kept alive, and that marking is the whole of what
    makes this survivable (docs/adr/0008, docs/adr/0009).
    """
    project = session.project
    standing_lines = (
        [
            "",
            "What the person who runs this project asked anybody working here to know:",
            standing.strip(),
        ]
        if standing.strip()
        else []
    )
    return "\n".join(
        [
            "This turn was sent by agent-desk, not by a person: you went idle and this project is "
            "switched on to keep going. Nobody is waiting at a prompt, so do not ask a question — "
            "where you would ask one, make the reasonable choice, write down what you chose, and "
            "carry on.",
            "",
            "If the work you were doing is not finished, continue it and finish it.",
            "",
            "If it is finished, then:",
            "",
            dispatch.go_looking(project),
            *standing_lines,
        ]
    )


async def kick_one(store: Store, arming: Kicking, session: Session) -> bool:
    """Send one session one more turn, and record every way that can end."""
    result = await asyncio.to_thread(
        dispatch.kick,
        arming.session_id or session.session_id,
        carry_on(arming, session, await store.project_note(_repo_key(session))),
        cwd=arming.cwd or session.cwd,
        agent_id=arming.short_id,
    )
    if result.started:
        await store.note_kick(arming.short_id)
        log.info("kicking.kicked", session=arming.short_id, project=session.project)
        return True

    # A limit is a wait, not a failure: nothing is broken, there is simply nothing to spend. The
    # switch stays on and the console comes back to it.
    if dispatch.looks_like_a_limit(result.detail):
        until = int(time.time() * 1000) + DEFAULT_LIMIT_WAIT_MS
        await store.kick_waits_until(arming.short_id, until)
        log.info("kicking.limited", session=arming.short_id, detail=result.detail)
        return False

    failures = await store.note_kick_failure(arming.short_id)
    log.warning("kicking.failed", session=arming.short_id, detail=result.detail)
    if failures >= FAILURES_BEFORE_DISARM:
        await store.stop_kicking(arming.short_id, why=f"two in a row failed: {result.detail}"[:300])
    return False


async def tick(store: Store) -> str:
    """One pass: at most one session is continued, and the id of the one that was.

    One per tick, across every switched-on session. Nothing here is urgent and a burst is the
    thing this file exists not to do.
    """
    armed = await store.kicked_sessions()
    if not armed:
        # The ordinary case on most consoles, and it costs nothing: no registry read, no thread.
        return ""

    now_ms = int(time.time() * 1000)
    live = await asyncio.to_thread(_sessions)
    for arming in armed:
        session = live.get(arming.short_id)
        if session is None or why_not_kick(arming, session, now_ms, _spent(arming, now_ms)):
            continue
        if await kick_one(store, arming, session):
            return arming.short_id
    return ""


async def run(store: Store) -> None:
    """The loop, held open for the life of the process by the TaskGroup the others use.

    It never raises out: a bad tick logs and waits for the next one.
    """
    while True:
        with contextlib.suppress(asyncio.CancelledError):
            try:
                await tick(store)
            except Exception:
                log.exception("kicking.tick_failed")
        await asyncio.sleep(TICK_SECONDS)
