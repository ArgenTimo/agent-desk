# ADR 0008 — an agent that finds its own work, inside a fence

**Status:** accepted · 2026-09-05

## Context

[0007](0007-a-loop-that-decides-when-not-what.md) drew a line and named the two loops on either
side of it. A loop that decides *when* to start something already approved is wrong by wasting an
agent-hour. A loop that decides *what* to do — reads a repository, judges what is worth doing,
writes its own tickets and starts on them — is wrong by producing "a night of confident work on
something nobody wanted, a queue full of tickets nobody asked for, and — the expensive part — a
record that looks exactly like a queue somebody chose."

Only the first was built. The owner now wants the second, in these words: when there is nothing
left to do, the agent should go through the project looking for bugs, technical debt, gaps in the
tests, vulnerabilities and rough edges, make tasks out of what it finds, and do them — until the
project is, in their word, *эталонный*: a reference.

That is a real thing to want and the reason is not laziness. The work it describes — the failing
edge case nobody wrote a test for, the module whose docstring stopped being true three phases ago,
the dependency with a known advisory — is exactly the work that never gets prioritised, because
every hour of it competes with a feature. An agent is good at it and never bored by it.

So this ADR does not argue that the earlier refusal was wrong. It argues about *which part* of it
was load-bearing, and fences the rest.

## What was actually dangerous

Re-read the sentence 0007 refused with. Three things are in it, and they are not equally bad.

**"Work nobody wanted"** — bad in proportion to what it costs to throw away. A branch in a
worktree costs a `git worktree remove`.

**"A queue full of tickets nobody asked for"** — worse, and it is worse for a specific reason: a
backlog is read as a record of decisions. Ten items somebody chose and forty a machine invented,
in one list, in the same font, is a list that has stopped meaning anything.

**"A record that looks exactly like a queue somebody chose"** — this is the whole of it. The
danger was never that a machine did work; it is that afterwards nobody can tell which work a human
asked for.

Everything below follows from that: **let it work, and never let its output be mistaken for
somebody's decision.**

## Decision

A project may be switched into **exploring**: when its queue is empty, one agent goes looking for
something to fix, fixes it in a worktree of its own, and stops.

- **A second switch, not the same one.** Arming the queue ([0007](0007-a-loop-that-decides-when-not-what.md))
  says "start what I put here". Exploring says "and when there is nothing, find something". They
  are different decisions and they are made separately; a project can be armed and not exploring,
  which is what every project is by default.
- **Only when the queue is empty.** Exploration never competes with work a human chose, and the
  moment something is queued, the queue wins.
- **Everything it produces is marked as its own.** A task it invents carries `source_kind`
  `found`, renders as *found by an agent* wherever it is shown, and is counted separately. The
  queue never mixes what somebody asked for with what a machine proposed, because that mixing is
  the failure this ADR exists to avoid.
- **It fixes; it does not design.** What it may look for is fixed and narrow: a defect, a missing
  or wrong test, a documented behaviour that is no longer true, a dependency with a known
  advisory, a piece of dead code. It may not add a feature, change an interface, or write anything
  into the ideas pool — that pool is a person's notebook, and a machine's proposals in it would be
  the tickets-nobody-asked-for failure wearing a different hat.
- **One thing at a time, and small.** The instruction it is given says: find *one* thing, make the
  smallest change that fixes it, prove it with a test, and stop. An agent asked to improve a
  project without a bound improves it until the context runs out.
- **A day's budget, not an hour's.** Exploration is not urgent by definition. At most a stated
  number of self-found runs per day, one at a time, and the same two-failures-and-it-disarms rule
  as the queue.
- **It never merges.** Every result is a branch somebody reads. That is the property that makes
  all of this survivable, and it is the one thing that must not be relaxed later "to save a click".

  **Amended the same day, by the owner: it merges, when the project's own gate passes on it.**
  Recorded rather than quietly edited, because the paragraph above is the argument this ADR was
  written to make and it deserves to be read next to what replaced it.

  What was actually being bought by "a human reads every branch" was *not breaking the project*,
  and in a repository whose owner is one person with a queue of agents, that review was not
  happening — the branches were piling up unread, which buys nothing at all. So the guarantee is
  mechanical now and narrower: `agent_desk/land.py` runs the repository's **own** gate — its
  `make verify`, its exit code, no judgement — in the agent's worktree, and merges only if it
  passes. It refuses a dirty checkout, a branch with no commits, a repository with no gate to
  check against, and a merge that conflicts, which it undoes at once.

  That is a weaker promise about taste and a stronger one about breakage. It is also *checkable*,
  which the promise about reading was not. The thing to watch is unchanged: branches kept over
  branches made, and a merge commit that says `agent:` is how anybody tells them apart afterwards.

## Why the marking is the whole of it

A queue with two kinds of row in it is only honest if the two kinds *look* different. So: the
switch says what it will do in a sentence before it is pressed; the task says **found by an
agent** wherever it appears; the project card counts them apart; and the branch name says it too.
Somebody looking at this repository in a month can tell, without asking, which work was chosen and
which was proposed.

That is also the measurement. If a month of exploring produces branches nobody keeps, the answer
is not to tune the prompt — it is to switch it off, and the count is what says so.

## Consequences

**Accepted: the console now spends money while nobody is watching it.** Bounded to an armed
project, an empty queue, a day's budget, one agent, and a console that is running. The number to
watch is branches kept over branches made.

**Accepted: it will sometimes be wrong about what is worth fixing.** That is the cost of the
feature and it is paid in worktrees, which are free. What it must never be is *confusing* — hence
the marking.

**Rejected: exploring a repository this console does not own.** Only a project somebody switched
on, and the switch lives on that project's own page.

**Rejected: writing ideas.** The pool is the human's. An agent that fills it is the failure
[05-ideas.md](../05-ideas.md) is about, and no amount of marking would fix it: an idea is a thing
somebody *had*.

**Amended: it merges what its own gate accepts** (above). Opening pull requests and filing what it
finds in a tracker are still refused: those are somebody else's queue, which is
[adr/0005](0005-one-door-out-to-a-tracker.md) unchanged.

**Rejected: a second agent while one is exploring.** The seat rule of
[0007](0007-a-loop-that-decides-when-not-what.md) covers exploration too — one agent per project,
whatever started it.

## How it is enforced

The switch, the budget and the empty-queue precondition live in the same module as the loop, and
the tests are again mostly about what does *not* happen: not while something is queued, not
without the switch, not past the day's budget, not twice at once, and not after two failures. The
marking is asserted where it matters — the task's kind, and the words on the card.
