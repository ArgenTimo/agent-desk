# ADR 0013 — back to observing

**Status:** accepted · 2026-09-27

## Context

[01-vision.md](../01-vision.md) says what this program is: it does not run agents; it observes and
it remembers. Then the console grew hands. [0006](0006-the-desk-may-start-work.md) let it start an
agent on a click, [0007](0007-a-loop-that-decides-when-not-what.md) let a loop decide *when*,
[0008](0008-an-agent-that-finds-its-own-work.md) sent an agent to find its own work and — as
amended — merged and pushed what the project's gate accepted,
[0009](0009-a-session-that-is-not-allowed-to-idle.md) kept a switched-on session going whenever it
went idle, and [0012](0012-the-one-irreversible-thing.md) let it close a session whose canary was
lost.

Each of those was argued carefully, and each document is still a good account of why it was
wanted. What they could not know at the time is what would actually be used. The research in
`_research/02_capabilities_and_scope.md` §3 counted it from the live database:

- **Exploring:** six runs, no merges. The gate `land.py` ran was not hermetic, and it merged and
  pushed by default.
- **Kicking:** no use at all. It was the one path that wrote into a running session's context on a
  timer — switched on by a person, but against [0002](0002-read-first-never-interrupt.md) in
  spirit — and its loop started with every console whether anybody had switched anything on.
- **Closing sessions:** no use, no canaries to lose. The one irreversible act in the console, for a
  thing `claude stop` already does by hand.

What is used every day is the board and the inbox. The criterion the research applied is whether a
capability helps somebody running three to five sessions *see and not lose the thread*, or does
what the CLI or ai-worker already does better. The three above fail it, and they are the three that
act on their own. `_research/06_backlog.md` item S1 is this change.

## Decision

**Explore and land, kicking, and closing sessions are deleted** — not switched off, deleted.

- Exploring: the switch, its budget, the loop's branch that went looking, and the instruction
  `dispatch.go_looking` gave. Autonomous work belongs to ai-worker, whose own lane shipped refusing
  for the same reasons.
- Landing: `agent_desk/land.py`, its route, the action on the "would not merge" blocker, the `land`
  and `push` permissions a workbench step could be given, and the settling pass that offered a
  `found` branch to the gate. Nothing in this console merges or pushes.
- Kicking: the loop, its per-session and per-project switches, the "on a break until" state on a
  card, the "stopped being kept going" blocker, and the "out until" on a plan.
- Closing sessions: `agent_desk/tidying.py`, the pass that closed them, and its switch. A lost
  canary is still flagged on the card and still offers a fresh session beside it; ending the old
  one is something a person does in the terminal that has it.

**Answering a background session from its card stays.** It is one message, typed by a person, sent
by a click — the case [0002](0002-read-first-never-interrupt.md) was written *for*. The door it
uses (`dispatch.kick`: `stop`, then `--bg --resume`) and the rule for which sessions it is offered
to (`dispatch.answerable`) stay with it.

**Dispatch, autostart and the workbench engine stay, frozen.** They are behind `AGENT_DESK_HANDS`,
off by default (A6 in the backlog): the code and its tests remain, changes are fixes only, and a
console nobody configured starts no agent. The background reading of the idea pool keeps its own
switch and now lives with the rest of that pass, in `agent_desk/ideas/appraise.py`.

## Consequences

- The modules, routes, buttons and tests of the three are gone: `/explore`, `/tidy-sessions`,
  `/projects/kicking`, `/sessions/{id}/kicking` and `/tasks/{id}/land` answer as routes that do not
  exist. [0008](0008-an-agent-that-finds-its-own-work.md),
  [0009](0009-a-session-that-is-not-allowed-to-idle.md) and
  [0012](0012-the-one-irreversible-thing.md) are superseded by this document and otherwise left
  as they were written.
- **The tables stay.** `kicking`, `autostart.exploring_at`, `per_day`, `tidying_at` and
  `task.landed` are still in the schema, and no migration drops them: a migration that destroys
  data to tidy code is the wrong way round. Nothing writes them. What was already written is still
  read where it means something — a task marked **found by an agent** keeps its mark, a branch the
  gate refused is still a blocker (without the button that ran the gate again), and the deferral
  that waits for a green gate reads the last result recorded.
- **Getting any of it back** starts from git history, where every line of it is, and from the
  three ADRs, which say what each fence was for. It comes back as a new decision in a new
  document, measured against the same question — not as a revert.
