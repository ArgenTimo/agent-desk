# ADR 0007 — a loop that decides *when*, never *what*

**Status:** accepted · 2026-09-04

## Context

[0006](0006-the-desk-may-start-work.md) allowed the console to start an agent on a written
instruction, and refused the obvious next thing in as many words: *"no automatic dispatch — not on
a schedule, not when a rate limit lifts, not when an agent goes idle, not when a tracker has an
unassigned ticket. Every one of those is a rule that decides when to start work, which is the
queue [08-non-goals.md](../08-non-goals.md) §2 refuses and the judgement this tool cannot see
enough to have. If it is ever wanted, it is the next ADR, and it needs an argument about what
happens when the rule is wrong at three in the morning."*

It is wanted. The inbox has it three times over: pick the work back up when the model's rate limit
lifts, do not let agents stand idle while there is work, and re-check a blocker once a human says
it is cleared. Behind all three is one sentence the owner wrote down: *the person never touches an
agent's session or the project's code by hand.*

So this ADR owes the argument it was told to bring.

## The distinction the whole thing rests on

There are two loops hiding inside "make it automatic", and they are not the same risk.

**A loop that decides *what* to do.** It reads a repository, judges what is worth doing, writes
tickets for itself and starts working on them. Wrong at three in the morning, this produces a
night of confident work on something nobody wanted, a queue full of tickets nobody asked for, and
— the expensive part — a *record* that looks exactly like a queue somebody chose. This is the
failure [05-ideas.md](../05-ideas.md) is about: the information lost between an idea and a written
ticket is a human deciding it is worth doing, and a queue that fills itself is a queue nobody
trusts.

**A loop that decides *when* to start something already approved.** Wrong at three in the morning,
it starts work the human queued, in a worktree, earlier or later than they imagined. The failure
mode is a wasted agent-hour and a branch to delete.

Those are different by an order of magnitude, and only the second one is decided here.

## Decision

**A human puts work in a queue. A loop decides when to start it, and nothing else.**

- **The loop never invents a task.** Every task it starts was written by a person and put in the
  queue by a person clicking a button. It does not read a tracker for unassigned tickets, does not
  scan a repository for things worth fixing, and does not turn an idea into work — an idea becomes
  a task the same way it becomes a ticket, by somebody deciding it should.
- **Armed per project, off everywhere by default.** A project with nothing switched on behaves
  exactly as it did before this ADR. Arming is a switch in that project's own settings panel, and
  the switch says what it will do.
- **A budget, and it is small.** At most one auto-started agent running per project at a time, and
  at most a stated number of starts per hour. The budget is checked before every start; a project
  that has spent it waits, visibly, rather than queueing more.
- **It only runs while the console does.** This is not a daemon and does not install one. Close
  the console and nothing starts. That is a real limitation and it is also the simplest kill
  switch there is.
- **Failure disarms it.** Two consecutive tasks that fail to start disarm that project and say
  why. A rule that keeps firing into a broken condition is the three-in-the-morning failure in its
  most ordinary form — a full disk, an expired token, a dirty worktree — and the answer to it is
  to stop, not to retry harder.
- **Everything is on the board.** A task carries who queued it and when, and once it starts it is
  a session like any other: labelled `agent`, showing what it is doing, stoppable.

Nothing about [0006](0006-the-desk-may-start-work.md) is weakened. The dispatch itself is the same
one: a new agent, in a worktree of its own, with the permission model untouched, and never a
message into a session that is already running.

## What is still refused

**An agent that finds its own work.** "If there are no tasks, go through the project, look for
bugs, tech debt, rough edges, and create tickets for them" is in the inbox and it is not this.
That is the first loop above, and it needs its own argument — about who reads the tickets it
writes, and about what a week of them does to a backlog somebody has to trust.

**Reading a tracker to find work.** Same reason, plus [0005](0005-one-door-out-to-a-tracker.md)
already refuses reading Jira back. A ticket becomes a task here by somebody choosing it.

**Queueing without a human.** Nothing enqueues itself. Not the classifier, not an answer run, not
a failed task retrying itself, not the console noticing an idle agent and finding it something to
do.

**Retrying.** A task that failed stays failed and says so. Retry is a click.

## Consequences

**Accepted: this is a queue, and [08-non-goals.md](../08-non-goals.md) §4 said there would not be
one.** That section is about an idea inbox growing priorities, assignees and estimates until it is
a tracker nobody maintains. This queue holds approved work with no priority, no assignee and no
estimate — it is a list of things somebody said to do, in the order they said it. The distinction
is thin enough to be worth watching: if a field for "who" or "how big" is ever proposed here, this
paragraph is the argument against it.

**Accepted: the console is now something that acts while nobody is looking at it.** Bounded to a
started console, an armed project, a small budget and a queue somebody filled — but true, and it
is the sentence a reader of [01-vision.md](../01-vision.md) should have in mind, because that
document describes a tool that only reads.

**Accepted: work can start at an awkward moment.** The loop cannot see that a human is mid-thought
in that repository. It works in a worktree, which is what makes that survivable rather than
serious.

**Measured, from the first day:** starts per project per day, and how many of them produced a
branch anybody kept. A loop that starts ten agents a day and produces nothing is not a feature
that needs tuning; it is a feature to switch off, and the number is what says so.

## How it is enforced

The budget, the arming and the disarm-on-failure live in one module with the loop, and the tests
that matter are the ones that assert it does *not* start: not when the project is not armed, not
when the budget is spent, not when something is already running, not when the queue is empty, and
not after two failures. The dispatch path underneath is
[0006](0006-the-desk-may-start-work.md)'s, unchanged, and its own tests still hold it.
