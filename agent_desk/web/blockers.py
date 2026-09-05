"""What is actually stopped, computed from what this program already knows.

The right column drew three placeholders for a year and said so on the card: "a blocker this
program cannot observe is one it will not invent." That was the right refusal — a guessed blocker
is the guessed status CLAUDE.md's fifth rule is about — but it was refusing the wrong question.
Every one of these is a *fact this console wrote down itself*, not an inference about somebody
else's session:

- a task it started that failed, and nobody has retried;
- a branch an agent finished that its project's own gate would not take (docs/adr/0008);
- a project that switched itself off after two failures (docs/adr/0007);
- a session that switched itself off after two (docs/adr/0009);
- a question this console asked a model that came back an error.

What is deliberately *not* here is the thing the placeholders promised: "waiting on a person" and
"waiting on a run". Neither is on disk. The board renders the first as an inference, in amber,
next to the observation it was made from, and it stays there — a red card claiming somebody is
blocked is exactly the failure the column was drawn empty to avoid.

Red means stopped, and everything in this module is stopped. A rate limit is not: it is a wait,
it comes back on its own, and it renders as a break rather than a blocker.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_desk.store.repo import Store

# How many are shown. A column of forty is a column nobody reads, and the newest are the ones
# somebody can still do something about.
MOST_SHOWN = 12


@dataclass(frozen=True)
class Blocker:
    """One thing that has stopped, and the one action that would unstop it."""

    kind: str
    what: str
    why: str
    when: int
    # Where to go: the card this is about, in the same `kind:id` shape the board's cards drag as.
    card: str = ""
    # The form that would deal with it, where there is one. A blocker with nothing to press is
    # still worth showing; a blocker whose fix is one click and does not offer it is not.
    action: str = ""
    action_says: str = ""


async def blockers(store: Store) -> list[Blocker]:
    """Everything that is stopped, newest first. Never raises: this renders a column."""
    found: list[Blocker] = []

    for task in await store.tasks(limit=200):
        if task.failed_at:
            found.append(
                Blocker(
                    kind="task",
                    what=task.title,
                    why=task.detail or "it failed and said nothing",
                    when=task.failed_at,
                    action=f"/tasks/{task.id}/retry",
                    action_says="try it again",
                )
            )
        # A branch that finished and did not land is work sitting in a worktree nobody has read.
        elif task.finished_at and task.detail and task.detail.startswith("not merged"):
            found.append(
                Blocker(
                    kind="branch",
                    what=task.title,
                    why=task.detail,
                    when=task.finished_at,
                )
            )

    for arming in await store.switched_off_projects():
        if arming.disarmed_why:
            found.append(
                Blocker(
                    kind="project",
                    what=arming.repo_key.split(":")[-1],
                    why=f"it stopped starting work: {arming.disarmed_why}",
                    when=arming.armed_at or 0,
                    card=f"project:{arming.repo_key}",
                )
            )

    for kicked in await store.switched_off_sessions():
        if kicked.disarmed_why:
            found.append(
                Blocker(
                    kind="session",
                    what=kicked.short_id,
                    why=f"it stopped being kept going: {kicked.disarmed_why}",
                    when=kicked.kicked_at or 0,
                )
            )

    for block in await store.blocks(limit=60):
        if block.state == "failed" and block.finished_at:
            found.append(
                Blocker(
                    kind="answer",
                    what=block.input.splitlines()[0][:60] if block.input else "a question",
                    why=block.error or "the run failed and said nothing",
                    when=block.finished_at,
                )
            )

    found.sort(key=lambda one: one.when, reverse=True)
    return found[:MOST_SHOWN]
