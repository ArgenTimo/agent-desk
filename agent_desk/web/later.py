"""The loop that brings back what somebody put off (031-deferred.sql).

*"Отложенная задача должна иметь момент срабатывания… и в этот момент срабатывать сама."*

`agent_desk/ideas/waking.py` decides what a moment is and whether it has come. This is the part
that goes and looks: once a minute it reads the ideas that are waiting for one, works out the two
facts a condition can be about, and for each moment that has arrived puts the work in the queue.

**It queues; it does not start.** That is the whole of how this stays inside docs/adr/0007 — the
loop decides *when*, never *what*. What to do was decided by the person who wrote the idea and
deferred it; whether an agent may then be started on it without asking again is the arming switch
that already exists, unchanged, in `autostart.py`. On a console where nothing is armed, a moment
arriving produces a task in the queue with somebody's name on it, and that is exactly what "напомни
завтра" should produce.

It lives under `web/` because it queues work, and queueing is a door only `web/` may open
(docs/adr/0006).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog

from agent_desk.ideas import waking
from agent_desk.observe import registry
from agent_desk.observe.shape import repository_of
from agent_desk.store.repo import Idea, Store

log = structlog.get_logger()

# Once a minute. A moment that was named to the day does not need to be noticed to the second, and
# a moment that was named as a condition is bounded below by how fast the condition can change —
# which on this machine is the length of an agent's turn.
TICK_SECONDS = 60.0


async def anything_running() -> bool:
    """Whether this machine is busy, which is what "когда освободится" means here.

    The registry's own word for it. `busy` is a fact a session writes about itself
    (docs/03-session-observation.md); nothing here infers it from silence, so a machine full of
    sessions sitting at their prompts reads as free — which is what it is.
    """
    sessions = await asyncio.to_thread(registry.read_registry)
    return any(session.status in ("busy", "shell") for session in sessions.sessions)


async def gate_is_green(store: Store, repo_key: str) -> bool:
    """Whether the last thing this project finished got through its own gate.

    Not by running one. This console never runs a command inside a repository it watches — the
    gate it knows about is the one `land.land` already ran in an agent's worktree, and the result
    of that is recorded on the task (docs/adr/0008).

    So the answer is: nothing of this project's is in flight, and the last branch that was offered
    to it got through. **A project whose gate has never run is not green**, because nothing has
    been checked — reporting that as green would be the inferred status CLAUDE.md's fifth rule is
    about, and here it would start work on the strength of a gate nobody ran.
    """
    tasks = [task for task in await store.tasks(repo_key=repo_key) if task.started_at is not None]
    if any(task.finished_at is None and task.failed_at is None for task in tasks):
        return False
    ran = [task for task in tasks if task.landed is not None]
    if not ran:
        return False
    return bool(max(ran, key=lambda task: task.started_at or 0).landed)


async def tick(store: Store) -> int:
    """One pass. Returns how many moments fired, which is what the test asserts on."""
    waiting = await store.deferred_ideas()
    if not waiting:
        return 0

    now = datetime.now(UTC)
    # Read once for the whole pass rather than once per idea: five deferred ideas must not cost
    # five registry reads, and they would all get the same answer anyway.
    busy = await anything_running()
    green: dict[str, bool] = {}

    fired = 0
    for idea in waiting:
        wake = waking.Wake(at=idea.wakes_at, when=idea.wakes_when)
        repo_key = idea.project_key or ""
        if wake.when == "gate" and repo_key not in green:
            green[repo_key] = bool(repo_key) and await gate_is_green(store, repo_key)
        if not waking.has_come(
            wake,
            now=now,
            anything_running=busy,
            gate_is_green=green.get(repo_key, False),
        ):
            continue
        # Whoever gets the row is the one that acts on it. Two passes overlapping would otherwise
        # both queue the same work.
        if not await store.idea_woke(idea.id):
            continue
        fired += 1
        await _queue(store, idea)
    return fired


async def _queue(store: Store, idea: Idea) -> None:
    """Put the deferred work in the queue, where a checkout can be found for it.

    An idea with no project, or a project with no checkout on this machine, still fires: the
    moment came, and the idea is no longer waiting for one. It simply lands back in the pool as an
    ordinary idea instead of as a queued task, which is visible — where a moment that quietly
    never arrived was not.
    """
    if not idea.project_key:
        log.info("later.woke_without_a_project", idea=idea.id)
        return

    where = await asyncio.to_thread(_a_checkout_of, idea.project_key)
    if where is None:
        log.info("later.woke_without_a_checkout", idea=idea.id, project=idea.project_key)
        return

    await store.queue_task(
        repo_key=idea.project_key,
        cwd=where,
        title=idea.summary[:60],
        instruction=idea.text,
        source_kind="deferred",
        source_ref=idea.id,
    )
    log.info("later.woke", idea=idea.id, project=idea.project_key)


def _a_checkout_of(repo_key: str) -> str | None:
    """Somewhere on this machine that this project is checked out, from the registry's own rows."""
    for session in registry.read_registry().sessions:
        if repository_of(session.cwd).key == repo_key:
            return session.cwd
    return None


async def run(store: Store) -> None:
    """The loop, for the life of the console.

    Same shape as the other three and for the same reasons: a bad tick logs and waits, and a
    cancel goes through rather than being swallowed — `app.lifespan` cancels this and then waits
    for it, and a tick sits in a thread for as long as a registry read takes.
    """
    while True:
        try:
            await tick(store)
        except Exception:
            log.exception("later.tick_failed")
        await asyncio.sleep(TICK_SECONDS)
