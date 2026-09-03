# Roadmap

Five phases to v1, and a page for what comes after it. Each has a **done-when** criterion that is observable from outside the code — not
"the module is written" but "the thing it was for is true". A phase is not done because its tests
pass.

The estimates are working days for one developer with an agent, and they assume the mechanisms of
[03-session-observation.md](03-session-observation.md) hold as recorded.

## Phase 0 — Harness · done

Repository, documentation, the `.claude/` skillset with its profile filled, build scaffolding,
and a green `make gate` on an empty implementation.

**Done when:** `make install && make verify` is green on a fresh clone.

## Phase 1 — The board · ~1–2 days

`observe` reads the registry and the transcript tails; `web` renders the board and pushes updates
over SSE. No input field, no store, no model call. Read-only, throughout.

Order: registry reader with the `procStart` liveness check → transcript tail reader → the board
template → SSE → sorting and the waiting-inference flag.

**Done when:** for one full working day with three or more sessions running, every "what is that
agent doing" is answered from the board, and no terminal is opened to check. Count the times it
failed; that count is the Phase 1 report.

This phase is the whole value proposition. If it does not survive its own working day, nothing
after it matters, and the honest response is to fix the board rather than to start Phase 2.

## Phase 2 — Input, blocks, ideas · ~2.5–3 days

The store, the input field, non-blocking blocks, thread classification with its override, and the
ideas inbox with keep/discard and the three draft actions.

Order: store and migrations → block lifecycle with `answer` running `claude -p` → the input field
and streaming → idea capture and the card → thread classification, last, because it is the part
that needs the rest of it to evaluate against.

**Done when:** an idea that arrives mid-run is captured in under ten seconds without touching a
running session, and a week later the inbox still shows what the idea was and what was happening
when it arrived.

Watch the classifier: log every override click. A correction rate above roughly one in four means
the classifier is costing more attention than it saves, and the right answer is to default to a
new thread and let attaching be the click ([04-threads-and-blocks.md](04-threads-and-blocks.md)).

## Phase 3 — The one write path · built, and blocked

A button on a session row that sends a message to that session, showing it in full first
([adr/0002](adr/0002-read-first-never-interrupt.md)).

**Done when:** it has been used, and the session that received it did not lose its thread. If it
did, this phase is a mistake and reverting it is the finding.

**That day cannot happen yet, and the reason is the finding.** Everything a human touches is
built — the button, the panel, the message rendered in full beside the session it would reach, the
click, and `peer.py` as the single place a write could ever originate. What is missing is
delivery, and it is missing for a reason no amount of work here removes:

- The installed `claude` CLI publishes **no client** for its cross-session messaging socket: no
  subcommand, no flag, no SDK entry point. Checked at `2.1.259`.
- The protocol is internal to the binary, versioned (`peerProtocol`) and undocumented, and a
  message that arrives is routed into the receiving session's queue **as a prompt**. A guessed
  frame does not fail quietly; it lands in the middle of somebody's work, which is the one thing
  [adr/0002](adr/0002-read-first-never-interrupt.md) exists to prevent.
- Reading the socket key would not have helped: the CLI identifies a connecting process by kernel
  peer credentials, "never from the payload". The rule against opening those files
  ([07-security.md](07-security.md)) costs this phase nothing.

So `peer.send()` returns `needs_toolchain` and the panel says so, offering the text back to be
pasted by a human at a moment they choose — which is [08-non-goals.md](08-non-goals.md) §2 and §3
arriving at the same answer from the other direction.

**Entry condition for finishing it:** a supported client — a CLI subcommand, an SDK call, or a
published protocol. Not a reverse-engineered frame: that would be a write into another agent's
context on the strength of a guess, and it needs an ADR arguing for it rather than a commit.

## Phase 4 — The shared view · ~1–2 days, gated

A network bind, authentication, per-viewer authorisation, and a redacted read-only view — the
ideas list first, the board only if the disclosure decision of
[07-security.md](07-security.md) has actually been made.

**Entry condition, not a date:** a teammate has asked twice, unprompted. Until then this is a
feature for a hypothetical user, and building it early forces a security model onto a tool that
currently does not need one.

## Beyond v1

Meeting intake — reading a transcript, then attending live, then asking a question when called on —
is [`10-meeting-intake.md`](10-meeting-intake.md). It is not phased here, because it has no user
yet and its real blocker is consent rather than engineering.

Two things were done in the foundation for it and nothing else was: an idea records a **source**
rather than a session, and `observe/` is named as *a* source rather than *the* source. Both cost a
sentence and a column today; both are expensive to retrofit.

## What is measured

Two numbers, from the beginning, because they are the ones that say whether this worked:

- **Terminal opens to check status**, per day. Phase 1 exists to drive this to zero.
- **Ideas captured, and of those, promoted.** Capture with no promotion means the inbox is a
  drain, not a notebook — and the fix is in [05-ideas.md](05-ideas.md), not in more capture.
