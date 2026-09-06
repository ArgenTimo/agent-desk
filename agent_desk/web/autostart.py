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
import time
from pathlib import Path

import structlog

from agent_desk import dispatch, land
from agent_desk.observe import jobs, registry
from agent_desk.observe.model import JobEnd
from agent_desk.store.repo import Autostart, Store, Task
from agent_desk.tracker import github, jira
from agent_desk.web import blockers

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


def still_going(agent_id: str | None, live: set[str]) -> tuple[bool, JobEnd | None]:
    """Is this agent's work still ours to wait for, and what the CLI says about it.

    Two sources, in the order of how much they know. The job file (`observe/jobs.py`) says
    `working`, `done` or `failed` and is the only one that distinguishes them; the registry says
    only who is alive. Absence from the registry is the fallback for a job the CLI has forgotten,
    and it is a weak signal on purpose — a `--bg` process outlives the work it was started for, so
    presence in the registry proves nothing on its own.
    """
    if not agent_id:
        # A started task with no agent recorded is a thing this module cannot answer for, and the
        # safe answer to that is the one that changes nothing: it keeps its seat and it is not
        # settled.
        return True, None
    ended = jobs.read_job(agent_id)
    if ended is not None:
        return not ended.terminal, ended
    return agent_id in live, None


async def running_for(store: Store, repo_key: str, live: set[str]) -> int:
    """How many of this project's started tasks still have an agent on them.

    A task whose agent is over is over, whatever it achieved: this module does not judge the work,
    only whether the seat is free. Getting this wrong in the other direction is worse than it
    sounds — a finished `--bg` agent idles at its prompt for as long as the machine is up, and a
    seat rule that watched only the registry would hold that project's seat forever.
    """
    return len(
        [
            task
            for task in await store.tasks(repo_key=repo_key)
            if task.started_at is not None
            and task.failed_at is None
            and still_going(task.agent_id, live)[0]
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


async def about(store: Store, repo_key: str) -> dict[str, object]:
    """What is true in this project whatever the task is, for `dispatch.build_task`.

    One place, so that a note or a word added on a project's page reaches the queue, an
    exploration and a session being kept going — rather than the one path somebody remembered to
    wire it into (020-project-note.sql, 021-glossary.sql).
    """
    return {
        "standing": await store.project_note(repo_key),
        "glossary": [(term.term, term.means) for term in await store.terms(repo_key)],
    }


async def _start(store: Store, task: Task) -> None:
    """Start one claimed task, and record either half of what happens."""
    result = await asyncio.to_thread(
        dispatch.start,
        dispatch.build_task(
            task.instruction,
            project=task.title,
            **await about(store, task.repo_key),  # type: ignore[arg-type]
        ),
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


def _worktree_of(task: Task, ended: JobEnd | None = None) -> str:
    """The name this task's worktree was made under, which is how its branch is found.

    Preferring what the CLI recorded over what this program would derive: the branch it actually
    made is a fact in its job file, and re-deriving it is a second copy of its slug rules to keep
    in step. The derivation stays as the fallback for a job whose file has been tidied away.
    """
    if ended is not None and ended.worktree_branch.startswith("worktree-"):
        return ended.worktree_branch[len("worktree-") :]
    return dispatch._worktree_name(task.title)


async def settle(store: Store, live: set[str]) -> list[str]:
    """Notice the agents that are over, and mark what they were dispatched for as built.

    A dispatched agent has no way to report back and this program will not ask it to. What it can
    see is the state the CLI writes down for the job (`observe/jobs.py`), and that is the moment an
    idea somebody started work on leaves the list — a human who finds it was not built after all
    presses Keep (docs/05-ideas.md).

    It says nothing about whether the work was any good. "An agent was dispatched for this and it
    finished" is the whole of the claim about *quality*, and it is the only one available.

    It does say whether the agent ran at all, and that is a different claim. An agent that exits
    before its first turn — a worktree name the CLI will not take, a directory that is not a
    checkout — looks from the registry exactly like one that worked all night. Six of them once
    did, and every idea they were dispatched for was marked built. So a job the CLI calls `failed`
    fails the task, keeps its ideas in the list, and counts towards the two failures that disarm a
    project.

    The other half of the same mistake was the signal itself: absence from the registry. A `--bg`
    process outlives the work it was started for and idles at its prompt for as long as the machine
    is up, so an agent that *succeeds* is never absent, its task never settles and its seat is
    never given up. `still_going` is the fix and the job file is what it reads. Where the CLI has
    nothing to say — a job tidied away by `claude rm` — the weak signal is the fallback and the
    claim stays the weak one, because a guess in either direction is worse than the truth about
    what is known (CLAUDE.md, rule five).
    """
    settled: list[str] = []
    for task in await store.tasks():
        if task.started_at is None or task.finished_at or task.failed_at:
            continue
        going, ended = await asyncio.to_thread(still_going, task.agent_id, live)
        if going:
            continue

        if ended is not None and ended.failed:
            detail = ended.detail or "its agent exited without saying why"
            await store.task_failed(task.id, detail)
            failures = await store.note_failure(task.repo_key)
            log.warning("autostart.died", repo=task.repo_key, agent=task.agent_id, detail=detail)
            if failures >= FAILURES_BEFORE_DISARM:
                await store.disarm(task.repo_key, why=f"two in a row died: {detail}"[:300])
            continue

        await store.finish_task(task.id)

        # What it found, merged if the project's own gate passes on it (docs/adr/0008, as the
        # owner amended it). A failing gate leaves the branch exactly where it is and says why.
        if task.source_kind == "found":
            result = await asyncio.to_thread(land.land, task.cwd, _worktree_of(task, ended))
            await store.task_landed(task.id, result.detail, landed=result.landed)
            log.info("autostart.landed", repo=task.repo_key, landed=result.landed)

        for idea_id in (task.source_ref or "").split(","):
            idea = await store.idea(idea_id) if idea_id else None
            if idea is not None and idea.state != "done":
                await store.set_idea_state(idea.id, "done")
                settled.append(idea.id)
    return settled


async def _destination(store: Store, repo_key: str) -> jira.Destination | None:
    """Where this project's tracker is, if it has one somebody named a credential for.

    A project with a link and no variable has a link, not a destination — `tracker/jira.py` makes
    that judgement and this only asks it (docs/adr/0005).
    """
    for link in await store.links(repo_key):
        found = jira.destination_of(link.url, link.token_env)
        if found is not None:
            return found
    return None


async def pull_tickets(store: Store, arming: Autostart) -> int:
    """Put this project's unfinished tickets in the queue (docs/adr/0010). Returns how many.

    Three things keep this from being the backlog-that-fills-itself docs/adr/0005 refuses.

    It reads a queue **somebody else already decided**: a ticket in a tracker is a decision made
    in a system built for making it, which is exactly what an idea in the pool is not. It never
    touches the pool — what it writes is a *task*, marked `tracker` and counted apart from what a
    person queued here, so nobody a month later has to work out which was which. And it writes
    nothing back: no transition, no comment, no assignment.

    A ticket already in the queue is skipped by its key, so this is safe to run on every tick.
    """
    where = await _destination(store, arming.repo_key)
    if where is None:
        return 0
    read = await asyncio.to_thread(jira.read_board, where)
    if not read.ok:
        log.info("autostart.tracker_unread", repo=arming.repo_key, detail=read.detail)
        return 0

    # A ticket that says it is stuck does not go in the queue: an agent started on it would spend
    # a worktree discovering what the ticket already says. It is recorded as a blocker instead,
    # and skipping it silently would make a board full of blocked work look like an empty one
    # (026-tracker-blockers.sql).
    await store.replace_tracker_blockers(
        arming.repo_key,
        [(one.key, one.summary, one.blocked_by) for one in read.tickets if one.blocked],
    )

    already = {
        task.source_ref for task in await store.tasks(repo_key=arming.repo_key) if task.source_ref
    }
    queued = 0
    for ticket in read.tickets:
        if ticket.key in already or ticket.blocked:
            continue
        await store.queue_task(
            repo_key=arming.repo_key,
            cwd=arming.cwd or "",
            title=f"{ticket.key} · {ticket.summary}",
            instruction=(
                f"{ticket.summary}\n\nThis is {ticket.key} on the project's own board, and it was "
                "read from there rather than written here. Do what it asks. If the ticket turns "
                "out to be wrong, or to need somebody to decide something, say so and stop — "
                "nothing here transitions it, comments on it, or closes it."
            ),
            source_kind="tracker",
            source_ref=ticket.key,
        )
        queued += 1
    if queued:
        log.info("autostart.tracker_queued", repo=arming.repo_key, queued=queued)
    return queued


async def pull_requests(store: Store, arming: Autostart) -> int:
    """Record the pull requests waiting on somebody as blockers. Returns how many.

    "В качестве блокеров также могут висеть PR с github, которые ожидают ревью/апрува/мержа — для
    тех проектов, которые подключили гитхаб как коннектор."

    A pull request open for three days waiting on a review is a thing that has stopped, stopped on
    a *person*, and invisible from a board that only watches sessions. Read-only, and only where
    somebody named a credential on the project's GitHub link (`connectors.py`).
    """
    for link in await store.links(arming.repo_key):
        if not link.token_env:
            continue
        repo = github.repo_of(link.url)
        if not repo:
            continue
        read = await asyncio.to_thread(github.open_pulls, repo, link.token_env)
        if not read.ok:
            log.info("autostart.pulls_unread", repo=arming.repo_key, detail=read.detail)
            return 0
        await store.replace_pull_blockers(
            arming.repo_key,
            [(one.key, one.title, one.waiting_for, one.url) for one in read.pulls],
        )
        return len(read.pulls)
    return 0


async def check_claims(store: Store) -> int:
    """Look at the blockers somebody said were cleared, and say what is actually true.

    "Агенты запускают проверку в ближайший момент когда освободятся, проверяют блокер, и только
    если разблокировано — блок уходит."

    No agent is started for this and none is needed: every kind of blocker this console shows was
    computed from something it can look at again. A claim is checked by recomputing — if the thing
    is no longer stuck, the claim was right and both it and the blocker go; if it still is, the
    claim is answered with the reason it is still there, in the blocker's own words.

    That is a stronger check than an agent's opinion would be, and it costs nothing.
    """
    claims = await store.claims()
    waiting = [name for name, claim in claims.items() if claim.waiting]
    if not waiting:
        return 0

    still = {one.id: one for one in await blockers.blockers(store)}
    checked = 0
    for name in waiting:
        stuck = still.get(name)
        if stuck is None:
            # Not a blocker any more: whoever pressed the button was right, and there is nothing
            # left to show or to remember.
            await store.forget_claim(name)
            log.info("blockers.cleared", blocker=name)
        else:
            await store.claim_checked(name, f"still blocked — {stuck.why}")
            log.info("blockers.still_stuck", blocker=name)
        checked += 1
    return checked


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
        dispatch.build_task(
            dispatch.go_looking(project),
            project=project,
            **await about(store, arming.repo_key),  # type: ignore[arg-type]
        ),
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
        # And the switch that started *this*. Arming and exploring are two decisions
        # (docs/adr/0008), so disarming the queue leaves exploring exactly where it was — which
        # meant a project whose starts kept failing went looking again on the next tick, and the
        # one after, for as long as the console stayed open. The rule is that it stops.
        await store.explore(arming.repo_key, per_day=arming.per_day, on=False)
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
    # Anything somebody said was cleared, checked against what is actually true now. Before
    # starting work, because a blocker that has gone may be the reason something can start.
    await check_claims(store)

    for arming in armed:
        if not await why_not(store, arming.repo_key, live):
            task = await store.take_next_task(arming.repo_key)
            if task is not None:
                await _start(store, task)
                # One start per tick, across every project. Nothing here is urgent, and a burst is
                # the thing this file exists to not do.
                return task

        # Nothing queued here, but there may be something on the project's own board. A ticket
        # somebody wrote comes before anything an agent would find for itself (docs/adr/0010),
        # which is why this sits above the exploration and below the queue.
        # And what is waiting on a person over on GitHub, which never becomes queued work —
        # a review is not something an agent can give (docs/adr/0010).
        await pull_requests(store, arming)

        if not any(task.waiting for task in await store.tasks(repo_key=arming.repo_key)):
            if await pull_tickets(store, arming):
                return None

        # Nothing queued, and this project was told it may find something (docs/adr/0008).
        if not await _may_explore(store, arming, live):
            found = await _explore(store, arming)
            if found is not None:
                return found
    return None


async def run(store: Store) -> None:
    """The loop, held open for the life of the process by the same TaskGroup the blocks use.

    A bad tick logs and waits for the next one: a loop that took the console down with it would be
    a worse failure than anything it was started to do. Cancellation is the one thing it lets
    through, and it has to be — `app.lifespan` cancels this task on the way out and the group then
    *waits* for it, so a swallowed cancel is a console that will not close. And the cancel lands
    inside a tick rather than in the sleep more often than it looks: a tick sits in a thread for
    as long as `land.land` takes, which is `make install` and the repository's own gate.
    """
    while True:
        try:
            await tick(store)
        except Exception:
            log.exception("autostart.tick_failed")
        await asyncio.sleep(TICK_SECONDS)
