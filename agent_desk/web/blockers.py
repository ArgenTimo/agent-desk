"""What is actually stopped, what it is holding up by name, and which project it belongs to.

The right column drew three placeholders for a year and said so on the card: "a blocker this
program cannot observe is one it will not invent." That was the right refusal — a guessed blocker
is the guessed status CLAUDE.md's fifth rule is about — but it was refusing the wrong question.
Every card here is a *fact this console wrote down itself*, not an inference about somebody else's
session:

- a task it started that failed, and nobody has retried;
- a branch an agent finished that its project's own gate would not take (docs/adr/0008);
- a project that switched itself off after two failures (docs/adr/0007);
- a session that switched itself off after two (docs/adr/0009);
- a question this console asked a model that came back an error;
- a ticket or a pull request that somebody else's board says is waiting (docs/adr/0010).

What is deliberately *not* here is what the placeholders promised: "waiting on a person" and
"waiting on a run". Neither is on disk. The board renders the first as an inference, in amber, next
to the observation it was made from, and it stays there — a red card claiming somebody is blocked
is exactly the failure the column was drawn empty to avoid.

Red means stopped, and everything in this module is stopped. A rate limit is not: it is a wait, it
comes back on its own, and it renders as a break rather than a blocker.

## What each one holds up, and why it is a list rather than a number

The first version of this counted every piece of queued work in the blocker's project and put that
number on every blocker in it. With three blockers and five queued tasks, each card claimed to be
holding up five — the same five. That is not a measurement of anything, and it is the number the
card led with.

So each kind now names what it holds up, and only where the link is **causal and derivable**:

| a blocker of this kind | genuinely stops                                            |
|------------------------|------------------------------------------------------------|
| `project` (disarmed)   | every task queued for it — they cannot start while it is off |
| `task` (failed)        | the ideas that task was going to build                       |
| `branch` (not merged)  | the same, still unbuilt because the work never landed        |
| `ticket` / pull request| the idea this console filed as it, where it filed one        |
| `session`, `answer`    | nothing this console can see, and the card says so           |

Everything in that table is a link something wrote down: `task.source_ref` names the ideas a task
was started for, `filing` records where an idea went, and a disarmed project is the reason its own
queue cannot move. Nothing here infers a dependency from a shared project or from words, which
would be a picture of a guess in a column whose whole purpose is the opposite.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace

from agent_desk.observe.shape import repository_of
from agent_desk.store.repo import Idea, Store, Task

# How many are shown. A column of forty is a column nobody reads, and the newest are the ones
# somebody can still do something about.
MOST_SHOWN = 12

# How many of the things one blocker holds up are named on its card before it says "and four more".
# A card that lists twenty is a card that has stopped being a card.
MOST_NAMED = 5


# What can be opened from a blocker. An idea has a card of its own; a queued task is a row in a
# project's queue and has none, so naming it is all this can honestly offer.
HAS_A_CARD = {"idea"}


@dataclass(frozen=True)
class Held:
    """One thing a blocker is holding up, named rather than counted.

    `card` is a `kind:id` the workbench understands, so the thing that is stuck can be dragged out
    of the blocker onto the bench and read. A blocker that names what it is holding up and gives
    no way to open it has only moved the question along one step.
    """

    kind: str
    id: str
    title: str

    @property
    def card(self) -> str:
        """The card to open, where the thing has one. Empty otherwise, and the template then
        renders the title as text rather than as a link into a 404."""
        return f"{self.kind}:{self.id}" if self.kind in HAS_A_CARD else ""


@dataclass(frozen=True)
class Blocker:
    """One thing that has stopped, and the one action that would unstop it."""

    kind: str
    what: str
    why: str
    when: int
    # Which project it is about, where it is about one. Empty means this console genuinely does
    # not know of one — a question to a model that came back an error belongs to no project — and
    # the card says that rather than letting it read as an unfiltered blank.
    repo_key: str = ""
    # A name of its own, so this card can be dragged onto the workbench and opened like any other
    # — `kind:ref`, stable for as long as the thing is stuck, which is as long as the card exists.
    ref: str = ""
    # Where the thing it is about lives, in the same `kind:id` shape the board's cards drag as.
    card: str = ""
    # The form that would deal with it, where there is one. A blocker with nothing to press is
    # still worth showing; a blocker whose fix is one click and does not offer it is not.
    action: str = ""
    action_says: str = ""
    # The ideas and tasks this one is genuinely stopping, by name. See the table in the module
    # docstring for what "genuinely" is allowed to mean here.
    holding_up: tuple[Held, ...] = field(default=())
    # And roughly how long clearing it takes if it is a person who has to do it.
    roughly: str = ""
    # Somebody has said this is cleared and nothing has checked yet (029-blocker-checking.sql).
    claimed: bool = False
    checked: str = ""

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.ref}"

    @property
    def holds(self) -> int:
        return len(self.holding_up)

    @property
    def named(self) -> tuple[Held, ...]:
        """The ones the card lists."""
        return self.holding_up[:MOST_NAMED]

    @property
    def unnamed(self) -> int:
        """How many more there are than the card has room for."""
        return max(0, len(self.holding_up) - MOST_NAMED)

    @property
    def about_a_project(self) -> bool:
        return bool(self.repo_key)


# What each kind is, in the words somebody reading the column would use. The `kind` field is this
# program's word for it and belongs in the markup; this is what goes on the card.
PLAINLY = {
    "task": "a job that failed",
    "branch": "finished work that would not merge",
    "project": "a project that switched itself off",
    "session": "a session that stopped being kept going",
    "answer": "a question that came back an error",
    "ticket": "a ticket waiting on a person",
    "pull": "a pull request waiting for review",
}

# What clearing one usually costs a person, by kind. Stated as a range and named as a guess on the
# card, because the honest alternative — saying nothing — leaves somebody unable to decide whether
# to do it now or after lunch, and that is the decision the number is for.
ROUGHLY = {
    "ticket": "usually a few hours — it is waiting on a person",
    "pull": "as long as a review takes — it is waiting on a person",
    "project": "minutes — press the switch again once whatever broke is fixed",
    "session": "minutes — press the switch again",
    "branch": "as long as the gate takes, once the branch is fixed",
    "task": "as long as the task takes, once whatever stopped it is fixed",
    "answer": "moments — ask it again",
}


def _ideas_of(task: Task, ideas: dict[str, Idea]) -> list[Held]:
    """The ideas a task was started for, from the ids it recorded when it was queued.

    Not every task names one — work this console found for itself does not — and an id that no
    longer resolves is an idea somebody deleted. Both are ordinary, and both mean the task holds
    up nothing that can be named.
    """
    held = []
    for idea_id in (task.source_ref or "").split(","):
        idea = ideas.get(idea_id.strip())
        if idea is not None and idea.state != "done":
            held.append(Held(kind="idea", id=idea.id, title=idea.summary))
    return held


async def blockers(store: Store, only: str = "") -> list[Blocker]:
    """Everything that is stopped, newest first. Never raises: this renders a column.

    `only` narrows it to one project. A blocker that belongs to no project survives the narrowing,
    because hiding it behind a filter it was never part of would lose it entirely — but it says on
    its own card that it is not about a project, so it does not read as one of this project's.
    """
    found: list[Blocker] = []
    tasks = await store.tasks(limit=500)
    ideas = {idea.id: idea for idea in await store.ideas(limit=500)}
    claims = await store.claims()

    # Work that cannot start until its project is switched back on. Keyed by project, because that
    # is the only thing a disarmed switch actually stops.
    queued: dict[str, list[Held]] = {}
    for task in tasks:
        if not task.waiting:
            continue
        held = _ideas_of(task, ideas) or [Held(kind="task", id=task.id, title=task.title)]
        queued.setdefault(task.repo_key, []).extend(held)

    for task in tasks[:200]:
        if task.failed_at:
            found.append(
                Blocker(
                    kind="task",
                    ref=task.id,
                    repo_key=task.repo_key,
                    what=task.title,
                    why=task.detail or "it failed and said nothing",
                    when=task.failed_at,
                    action=f"/tasks/{task.id}/retry",
                    action_says="try it again",
                    holding_up=tuple(_ideas_of(task, ideas)),
                )
            )
        # A branch that finished and did not land is work sitting in a worktree nobody has read.
        elif task.finished_at and task.landed is False:
            found.append(
                Blocker(
                    kind="branch",
                    ref=task.id,
                    repo_key=task.repo_key,
                    what=task.title,
                    why=task.detail or "the gate would not take it",
                    when=task.finished_at,
                    holding_up=tuple(_ideas_of(task, ideas)),
                )
            )

    for arming in await store.switched_off_projects():
        if arming.disarmed_why:
            found.append(
                Blocker(
                    kind="project",
                    ref=arming.repo_key,
                    repo_key=arming.repo_key,
                    what=arming.repo_key.split(":")[-1],
                    why=f"it stopped starting work: {arming.disarmed_why}",
                    when=arming.armed_at or 0,
                    card=f"project:{arming.repo_key}",
                    holding_up=tuple(queued.get(arming.repo_key, ())),
                )
            )

    # A switched-off session belongs to the project it is checked out in. It used to belong to
    # nothing, which meant it showed under every project's filter and under none of their counts —
    # the "не правильно мапятся на проекты" of the report, and the one case here where the answer
    # was already on the row.
    for kicked in await store.switched_off_sessions():
        if not kicked.disarmed_why:
            continue
        where = await _project_of(kicked.cwd) if kicked.cwd else ""
        found.append(
            Blocker(
                kind="session",
                ref=kicked.short_id,
                repo_key=where,
                what=kicked.short_id,
                why=f"it stopped being kept going: {kicked.disarmed_why}",
                when=kicked.kicked_at or 0,
                card=f"session:{kicked.session_id}" if kicked.session_id else "",
            )
        )

    for block in await store.blocks(limit=60):
        if block.state == "failed" and block.finished_at:
            found.append(
                Blocker(
                    kind="answer",
                    ref=block.id,
                    what=block.input.splitlines()[0][:60] if block.input else "a question",
                    why=block.error or "the run failed and said nothing",
                    when=block.finished_at,
                )
            )

    # And what somebody else's board says is stuck. A quotation with a key, never a judgement:
    # this program does not decide that a ticket is blocked, it repeats that the ticket says so
    # (docs/adr/0010, CLAUDE.md rule five).
    #
    # What it holds up is the idea this console filed as it, where it filed one. That is a link
    # this program wrote down itself, which is the only kind it is allowed to draw.
    filed = {filing.issue_key: filing.idea_id for filing in await store.filings()}
    for ticket in await store.tracker_blockers():
        a_pull = ticket.key.startswith("#")
        idea = ideas.get(filed.get(ticket.key, ""))
        found.append(
            Blocker(
                # A pull request and a ticket both stop on a person, and they are still not the
                # same thing to somebody deciding what to do about one. The old column called both
                # "ticket" and left the `#` to explain it.
                kind="pull" if a_pull else "ticket",
                ref=ticket.key,
                repo_key=ticket.repo_key,
                what=f"{ticket.key} · {ticket.summary}",
                why=(ticket.said if a_pull else f"the ticket says: {ticket.said}"),
                when=ticket.seen_at,
                holding_up=(
                    (Held(kind="idea", id=idea.id, title=idea.summary),)
                    if idea is not None and idea.state != "done"
                    else ()
                ),
            )
        )

    # How long it usually takes, and whether somebody has already said it is cleared.
    found = [
        replace(
            one,
            roughly=ROUGHLY.get(one.kind, ""),
            claimed=one.id in claims and claims[one.id].waiting,
            checked=(claims[one.id].found or "") if one.id in claims else "",
        )
        for one in found
    ]

    if only:
        found = [one for one in found if one.repo_key in ("", only)]
    # Newest first, and within the same moment the ones holding something up come first: a blocker
    # with four ideas behind it is a different size of problem from one with none.
    found.sort(key=lambda one: (one.when, one.holds), reverse=True)
    return found[:MOST_SHOWN]


# Resolving a checkout to a project reads git, so it is done off the loop and remembered for the
# life of the process: a session's directory does not change project, and this runs on every
# render of the column.
_projects: dict[str, str] = {}


async def _project_of(cwd: str) -> str:
    if cwd not in _projects:
        try:
            _projects[cwd] = (await asyncio.to_thread(repository_of, cwd)).key
        except OSError:
            # A directory that has gone is a session whose project cannot be named. The blocker is
            # still real; it simply belongs to nothing, and that is what an empty key means.
            _projects[cwd] = ""
    return _projects[cwd]


async def one(store: Store, blocker_id: str) -> Blocker | None:
    """The blocker with this id, or `None` when it has been cleared.

    Recomputed rather than stored: a blocker is a *view* of facts that live elsewhere, and a copy
    of one would go stale the moment somebody retried the task it is about. Gone is the ordinary
    outcome here and it is not an error — it means the thing got unstuck.
    """
    return next((one for one in await blockers(store) if one.id == blocker_id), None)
