# ADR 0009 — a session that is not allowed to idle

**Status:** accepted · 2026-09-05

## Context

[0002](0002-read-first-never-interrupt.md) is the first rule in CLAUDE.md and the oldest thing in
this repository: *never write into a running session's context without an explicit human click.*
The argument was about cost. Reading `~/.claude/` is free and invisible to the agent being read;
sending a message is not — it lands in that session's context window and displaces work. A tool
that becomes a second source of interruption has destroyed the thing it was built to protect.

The owner wants the opposite behaviour, in these words: while this service is up it should make
other sessions — and its own — work to the end, not sit idle; picking the right prompt to continue
properly; and when there is nothing left to do, make something out of polishing the project, no
new features. A button on every session card turns it on. If a limit is hit, set a reactivation
for when it lifts and carry on.

They are not wrong about the problem. An agent that finished its turn at 03:00 and sits at its
prompt until somebody notices in the morning has burned six hours of a machine that was already
paid for, and every one of those hours was available. "Waiting for a human who is asleep" is not
a state worth protecting.

## What 0002 was actually protecting

Re-read its argument and three separate things are in it.

**A message costs context.** True, and unchanged. It is also *what a session is for*: the cost is
only waste when the message is worthless.

**An interruption displaces work.** This is the load-bearing half — but it is about *interrupting*,
and an idle session is by definition not working. Displacing nothing costs nothing.

**A background loop must not be the author of the interruption.** This is the part that survives
whole. The danger 0002 named was a *side effect*: a message arriving because a timer fired, with
no human anywhere in the chain, and nobody afterwards able to tell which turns a person asked for.

So the rule that is kept is not "never write". It is: **never write into a session that is
working, and never write anywhere no human switched on.**

## Decision

A session may be switched into **kicking**: while it is idle and the console is running, the
console continues it — one turn at a time, with a prompt, until the switch is turned off.

- **Per session, by a click, on that session's own card.** The switch of
  [0007](0007-a-loop-that-decides-when-not-what.md) and [0008](0008-an-agent-that-finds-its-own-work.md)
  again: one human act arms one thing, and the console says what it will do before it is pressed.
  What the click buys is a standing permission rather than a single message, and that is the whole
  of what this ADR changes about 0002.
- **Only into an idle session.** `status` is a fact in the registry, written by the session itself
  (docs/03-session-observation.md). `busy` is never kicked, ever, for any reason — that is 0002's
  surviving half and it is not negotiable.
- **Only a background session.** `claude --bg` has a documented door: `stop` keeps the
  conversation, and `--bg --resume <id>` continues it under the same id. An interactive terminal
  has no such door, and the one that exists — the peer socket — is authenticated by a key
  CLAUDE.md forbids this program to read. So a session running in somebody's terminal is shown as
  idle and left alone, and the card says why rather than offering a button that would lie.
- **It never invents the work.** Two prompts and no third. If the session was dispatched for a
  task that is not finished, it is told to carry on with it. If there is nothing outstanding, it
  is given the instruction [0008](0008-an-agent-that-finds-its-own-work.md) already wrote and
  already fenced: find one thing that is broken, fix it, prove it, stop — no features, no
  interfaces, no redesigns. The fence is reused rather than rebuilt, because it is the same fence.
- **Everything it sends is marked.** A kicked turn says, in the prompt itself, that a console sent
  it and no human is waiting on the other end. Somebody reading that transcript in a month can
  tell which turns were asked for and which were kept alive, which is the property
  [0008](0008-an-agent-that-finds-its-own-work.md) argued is the whole of it.
- **A budget, and two failures disarm it.** The same shape as the two loops before it. A kick that
  fails twice in a row switches the session off and says why, because a rule that keeps firing
  into a broken condition is the three-in-the-morning failure in its most ordinary form.
- **A limit is a wait, not a failure.** When the CLI refuses because the account is rate-limited,
  the switch stays on and the console records when to try again. Nothing is retried into a wall.

## What is deliberately not decided here

**Interactive sessions.** Wanted, and not possible without reading a credential. If a documented
way to address one appears, it arrives as an amendment to this document and not as a quiet edit to
a module.

**Judging whether the work was any good.** Unchanged from 0007: this console starts turns, it does
not review them. A kicked session that produces nothing useful is visible in the same place as an
explored branch nobody kept, and the answer is the same — switch it off.

## Consequences

**Accepted: the console now spends money on turns nobody read first.** Bounded to a session
somebody switched on, an idle state, a budget, and a console that is running. The number to watch
is the same as 0008's: work kept over work made.

**Accepted: a session's context fills faster.** That is what the switch is for, and it is why the
context percentage is on the card. A session kicked into its own context limit is a visible
outcome, not a hidden one.

**Rejected: kicking a busy session.** 0002's surviving half.

**Rejected: kicking every session because the console is running.** The switch is per session and
defaults to off. "All of them" is a click repeated, which is a human deciding each time.

## How it is enforced

The switch, the idle precondition, the budget and the limit window live in one module with the
other two loops, and the tests are again about what does *not* happen: not while it is busy, not
without the switch, not into an interactive session, not past the budget, not into a limit, and
not after two failures.
