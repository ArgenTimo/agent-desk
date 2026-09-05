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
from pathlib import Path

import structlog

from agent_desk import dispatch, land
from agent_desk.observe import registry
from agent_desk.store.repo import Autostart, Store, Task

log = structlog.get_logger()

# How often the queue is looked at. Slow on purpose: nothing here is urgent, and a tick that costs
# a subprocess is a tick worth spacing out.
TICK_SECONDS = 30.0

# The budget's window, and the hard ceiling on what one project may have running at once. One is
# not a placeholder: two agents in two worktrees of the same repository, started by a rule rather
# than by a person, is the shape of the mess docs/adr/0007 is careful about.
WINDOW_MS = 60 * 60 * 1000
AT_ONCE = 1

# A day, for the budget that bounds an agent looking for its own work. Exploration is not urgent
# by definition, and an hourly budget for it would be an invitation (docs/adr/0008).
DAY_MS = 24 * 60 * 60 * 1000

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


def _worktree_of(task: Task) -> str:
    """The name this task's worktree was made under, which is how its branch is found."""
    return dispatch._worktree_name(task.title)


async def settle(store: Store, live: set[str]) -> list[str]:
    """Notice the agents that have gone, and mark what they were dispatched for as built.

    A dispatched agent has no way to report back and this program will not ask it to; what it can
    see is that the session is no longer in the registry. That is the moment an idea somebody
    started work on leaves the list — and a human who finds it was not built after all presses
    Keep (docs/05-ideas.md).

    It says nothing about whether the work was any good. "An agent was dispatched for this and it
    finished" is the whole of the claim, and it is the only one available.
    """
    settled: list[str] = []
    for task in await store.tasks():
        if task.started_at is None or task.finished_at or task.failed_at:
            continue
        if task.agent_id is None or task.agent_id in live:
            continue
        await store.finish_task(task.id)

        # What it found, merged if the project's own gate passes on it (docs/adr/0008, as the
        # owner amended it). A failing gate leaves the branch exactly where it is and says why.
        if task.source_kind == "found":
            result = await asyncio.to_thread(land.land, task.cwd, _worktree_of(task))
            await store.task_landed(task.id, result.detail)
            log.info("autostart.landed", repo=task.repo_key, landed=result.landed)

        for idea_id in (task.source_ref or "").split(","):
            idea = await store.idea(idea_id) if idea_id else None
            if idea is not None and idea.state != "done":
                await store.set_idea_state(idea.id, "done")
                settled.append(idea.id)
    return settled


async def _may_explore(store: Store, arming: Autostart, live: set[str]) -> str:
    """Why this project may not go looking right now, or an empty string (docs/adr/0008).

    The queue comes first, always: exploration happens when there is nothing a human chose, and
    the moment something is queued the queue wins.
    """
    if not arming.exploring:
        return "not exploring"
    if await running_for(store, arming.repo_key, live) >= AT_ONCE:
        return "one is already running"
    if any(task.waiting for task in await store.tasks(repo_key=arming.repo_key)):
        return "there is queued work, which comes first"
    spent = await store.explored_since(arming.repo_key, int(time.time() * 1000) - DAY_MS)
    if spent >= arming.per_day:
        return f"the day's budget is spent ({spent} of {arming.per_day})"
    return ""


async def why_not_explore(store: Store, repo_key: str, live: set[str] | None = None) -> str:
    """The reason this project is not looking for work right now, in the loop's own words."""
    if live is None:
        live = await asyncio.to_thread(live_agents)
    return await _may_explore(store, await store.autostart(repo_key), live)


async def _explore(store: Store, arming: Autostart) -> Task | None:
    """Send one agent to find one thing worth fixing, and mark what it produces as its own.

    The marking is the whole of docs/adr/0008: a queue that mixes what somebody asked for with
    what a machine proposed is a queue that has stopped meaning anything.
    """
    # Where the switch was pressed, then this console's own checkout, then whatever an earlier
    # task in this project used. A project whose directory is not known is not explored.
    cwd = arming.cwd or ""
    if not cwd and arming.repo_key.startswith("desk:"):
        cwd = arming.repo_key.split(":", 1)[1]
    if not cwd:
        for task in await store.tasks(repo_key=arming.repo_key):
            cwd = task.cwd
            break
    if not cwd or not Path(cwd).is_dir():
        return None

    project = Path(cwd).name
    task = await store.queue_task(
        repo_key=arming.repo_key,
        cwd=cwd,
        title=f"looking for something to fix in {project}",
        instruction=dispatch.go_looking(project),
        source_kind="found",
    )
    await store.take_next_task(arming.repo_key)
    # The name is what its worktree and branch are called, so it is the same string the landing
    # looks for afterwards.
    result = await asyncio.to_thread(
        dispatch.start,
        dispatch.build_task(dispatch.go_looking(project), project=project),
        cwd=cwd,
        name=task.title,
    )
    if result.started:
        await store.task_started(task.id, result.agent_id)
        await store.clear_failures(arming.repo_key)
        log.info("autostart.exploring", repo=arming.repo_key, agent=result.agent_id)
        return task

    await store.task_failed(task.id, result.detail)
    failures = await store.note_failure(arming.repo_key)
    if failures >= FAILURES_BEFORE_DISARM:
        await store.disarm(
            arming.repo_key, why=f"two starts in a row failed: {result.detail}"[:300]
        )
    return task


async def tick(store: Store, live: set[str] | None = None) -> Task | None:
    """One pass: settle what has finished, then start at most one thing that may start."""
    armed = await store.armed_projects()
    started = await store.tasks()
    if not armed and not any(task.started_at and not task.finished_at for task in started):
        # The ordinary case on most consoles, and it costs nothing: no registry read, no thread.
        return None
    if live is None:
        live = await asyncio.to_thread(live_agents)

    await settle(store, live)

    for arming in armed:
        if not await why_not(store, arming.repo_key, live):
            task = await store.take_next_task(arming.repo_key)
            if task is not None:
                await _start(store, task)
                # One start per tick, across every project. Nothing here is urgent, and a burst is
                # the thing this file exists to not do.
                return task

        # Nothing queued, and this project was told it may find something (docs/adr/0008).
        if not await _may_explore(store, arming, live):
            found = await _explore(store, arming)
            if found is not None:
                return found
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
