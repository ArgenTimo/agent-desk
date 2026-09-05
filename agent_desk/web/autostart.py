"""The loop that decides *when*, and never *what* (docs/adr/0007).

Every task it starts was written by a person and put in the queue by a person clicking a button.
This module reads that queue and answers one question about the head of it: may it start now? Five
things say no, and the tests that matter are the ones that assert each of them.

It lives under `web/` because it dispatches, and dispatching is a door only `web/` may open
(docs/adr/0006). That it is a loop rather than a route does not change who is allowed to reach it:
what the loop starts is what a human queued.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

import structlog

from agent_desk import dispatch
from agent_desk.observe import registry
from agent_desk.store.repo import Store, Task

log = structlog.get_logger()

# How often the queue is looked at. Slow on purpose: nothing here is urgent, and a tick that costs
# a subprocess is a tick worth spacing out.
TICK_SECONDS = 30.0

# The budget's window, and the hard ceiling on what one project may have running at once. One is
# not a placeholder: two agents in two worktrees of the same repository, started by a rule rather
# than by a person, is the shape of the mess docs/adr/0007 is careful about.
WINDOW_MS = 60 * 60 * 1000
AT_ONCE = 1

# Two consecutive failures disarm a project. A rule that keeps firing into a broken condition — a
# full disk, an expired token, a worktree that will not create — is the three-in-the-morning
# failure in its most ordinary form, and the answer is to stop rather than to retry harder.
FAILURES_BEFORE_DISARM = 2


def live_agents() -> set[str]:
    """The short ids of the sessions running right now.

    A background session's `sessionId` begins with the short id `claude --bg` printed and
    `attach|logs|stop` take — `79586f63` and `79586f63-8e38-…` are the same session. That is how a
    task knows its agent has finished without this module asking the CLI anything: the registry is
    already read every two seconds for the board (docs/03-session-observation.md).
    """
    return {session.session_id.split("-")[0] for session in registry.read_registry().sessions}


async def running_for(store: Store, repo_key: str, live: set[str]) -> int:
    """How many of this project's started tasks still have an agent on them.

    A task whose agent has gone is finished, whatever it achieved: this module does not judge the
    work, only whether the seat is free.
    """
    return len(
        [
            task
            for task in await store.tasks(repo_key=repo_key)
            if task.started_at is not None
            and task.failed_at is None
            and (task.agent_id is None or task.agent_id in live)
        ]
    )


async def why_not(store: Store, repo_key: str, live: set[str] | None = None) -> str:
    """The reason this project may not start anything right now, or an empty string.

    One function, so that the console says exactly what the loop decided rather than its own
    guess at it.
    """
    arming = await store.autostart(repo_key)
    if not arming.armed:
        return "not armed"
    if live is None:
        live = await asyncio.to_thread(live_agents)
    if await running_for(store, repo_key, live) >= AT_ONCE:
        return "one is already running"
    spent = await store.started_since(repo_key, int(time.time() * 1000) - WINDOW_MS)
    if spent >= arming.per_hour:
        return f"the hour's budget is spent ({spent} of {arming.per_hour})"
    if not any(task.waiting for task in await store.tasks(repo_key=repo_key)):
        return "nothing is queued"
    return ""


async def _start(store: Store, task: Task) -> None:
    """Start one claimed task, and record either half of what happens."""
    result = await asyncio.to_thread(
        dispatch.start,
        dispatch.build_task(task.instruction, project=task.title),
        cwd=task.cwd,
        name=task.title,
    )
    if result.started:
        await store.task_started(task.id, result.agent_id)
        await store.clear_failures(task.repo_key)
        log.info("autostart.started", repo=task.repo_key, agent=result.agent_id)
        return

    await store.task_failed(task.id, result.detail)
    failures = await store.note_failure(task.repo_key)
    log.warning("autostart.failed", repo=task.repo_key, detail=result.detail, failures=failures)
    if failures >= FAILURES_BEFORE_DISARM:
        await store.disarm(task.repo_key, why=f"two starts in a row failed: {result.detail}"[:300])


async def tick(store: Store, live: set[str] | None = None) -> Task | None:
    """One pass over the armed projects. Returns what it started, for a test to assert on."""
    armed = await store.armed_projects()
    if not armed:
        # The ordinary case on most consoles, and it costs nothing: no registry read, no thread.
        return None
    if live is None:
        live = await asyncio.to_thread(live_agents)

    for arming in armed:
        if await why_not(store, arming.repo_key, live):
            continue
        task = await store.take_next_task(arming.repo_key)
        if task is None:
            continue
        await _start(store, task)
        # One start per tick, across every project. Nothing here is urgent, and a burst is the
        # thing this file exists to not do.
        return task
    return None


async def run(store: Store) -> None:
    """The loop, held open for the life of the process by the same TaskGroup the blocks use.

    It never raises out: a bad tick logs and waits for the next one. A loop that took the console
    down with it would be a worse failure than anything it was started to do.
    """
    while True:
        with contextlib.suppress(asyncio.CancelledError):
            try:
                await tick(store)
            except Exception:
                log.exception("autostart.tick_failed")
        await asyncio.sleep(TICK_SECONDS)
