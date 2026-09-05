# ADR 0006 — the desk may start work, and still may not steer it

**Status:** accepted · 2026-09-04

## Context

[0002](0002-read-first-never-interrupt.md) drew the line at a running session's context window and
[09-roadmap.md](../09-roadmap.md) recorded why the one write path stops there: the installed CLI
published no client for its cross-session socket, and a guessed frame lands in the middle of
somebody's work. [06-console.md](../06-console.md) put it as a rule about the whole console — *"no
button that starts, stops, or steers an interactive session"*.

Two things have changed since that was written, and only one of them is a decision.

**The owner asked for something the tool refuses to do.** An instruction typed into the console —
"tell Biba to test it again", or any of the ideas in the inbox — is written down, addressed, and
then waits for a click that cannot deliver it. What was wanted is that it *happens*. Their words
for the destination this project is heading toward: the person never touches an agent's session or
the project's code by hand; everything goes through the console and the tracker.

**The CLI grew a supported surface for exactly this.** At 2.1.261, `claude --bg` starts a session
in the background and prints an id; `-w/--worktree` gives that session a git worktree of its own;
`claude agents --json` lists what is running, for scripting, without a TTY; `logs`, `stop`, `rm`
and `respawn` complete the lifecycle. This is documented, versioned and scriptable — the entry
condition [09-roadmap.md](../09-roadmap.md) set for finishing Phase 3, met for the half of the
problem it turns out to solve.

It is worth being precise about which half. **There is still no client for writing into a session
that is already running.** That path is unchanged and still refused. What exists now is the
ability to *start a new one*.

## Decision

**A written instruction, on a human click, may start a new background agent** in the project it
names, in a git worktree of its own, with that instruction as its prompt.

- **The click is the send button.** An instruction is a person saying what should happen, so it
  starts an agent — that is the whole trigger, and it was narrowed twice before it was widened to
  this. A console whose answer to "do this" is "here are the words, carry them over yourself" has
  not done the thing it was asked; that was the honest answer while nothing could be started, and
  it stopped being the honest answer the day something could.

  Two things bound it and both are load-bearing. **What is read as an instruction is a run's
  judgement, and it can be wrong** — so a question is answered and never acted on, a misfire lands
  in a worktree nobody has to keep, and every dispatch is announced with the id and a button that
  stops it. And **no machine signal is ever the trigger**: a schedule, an idle agent, a ticket
  appearing are [0007](0007-a-loop-that-decides-when-not-what.md)'s subject, with its own limits.

  What is *not* started is the case where nothing says where: an instruction naming no session and
  with no card dropped in produces the message and asks which project it meant. Picking a
  repository to start work in would be a guess with a worktree at the end of it.
- **Starting is not interrupting.** What [0002](0002-read-first-never-interrupt.md) protects is a
  *running* agent's context window; a session that does not exist yet has none to displace. The
  property that made this tool safe to point at a working session — reading is invisible to the
  agent being read — is untouched.
- **A worktree of its own.** The observed checkout is not where the work happens, which is the
  substance of CLAUDE.md's second rule: this program still edits no file in a repository it
  watches. `git worktree add` writes metadata under that repository's `.git`, and that is stated
  here rather than hidden: it is the same command the human runs by hand for every task, and it is
  run by the CLI, on a click, in the directory they pointed at.
- **The CLI's own permission model applies, unweakened.** agent-desk passes
  `--dangerously-skip-permissions` and `--allow-dangerously-skip-permissions` **never**, under any
  setting, from any route. A dispatched agent asks for what it needs exactly as the same agent
  would if the human had started it in a terminal.
- **One module, one importer.** `agent_desk/dispatch.py` joins `peer.py` and `tracker/` as a door
  only `agent_desk/web/` may import, in the same import-graph test.
- **Every dispatch is recorded and visible**: which instruction, which project, which agent id,
  and when. The board shows background agents beside the interactive ones, because a thing this
  console started is a thing it must show.
- **Stoppable, not steerable.** A dispatched agent can be stopped from the console. It cannot be
  sent a follow-up: that is the wall of [0002](0002-read-first-never-interrupt.md), in exactly the
  place it has always been. What replaces a follow-up is reading what it did and starting another.

## Why this is not the failure 0002 was about

The failure was: *a background loop writes into an agent's context, the board looks excellent, and
the runs behind it get slower and more confused.* Every clause of that is still forbidden. There
is no loop; a person clicks. Nothing enters a running context window. Nothing this program does is
invisible to the person who caused it.

What this ADR gives up is a smaller and different thing: **the console is no longer purely a
reader.** It observes, and on a click it starts. That sentence is now in
[06-console.md](../06-console.md) too, because a rule that lives only in an ADR is a rule the next
reader of the console document does not know about.

## Consequences

**Accepted: a dispatched agent can be wrong, and it costs.** It is a whole session doing work
nobody watched it start. Three things bound that: the human wrote the instruction and pressed the
button, the work happens in a worktree that is trivially thrown away, and the session is visible
and stoppable from the moment it exists.

**Accepted: the board now shows work this program caused.** That is not a cost, it is the point —
but it means the board is no longer a pure observation of somebody else's machine, and a reader of
[03-session-observation.md](../03-session-observation.md) should know it.

**Rejected: bypassing permissions.** The flags exist and this program does not pass them. An agent
that cannot ask a human for permission is an agent this console cannot honestly claim a human is
standing behind.

**Rejected: steering a running session.** No follow-up messages, no injected keystrokes, no
`tmux send-keys` ([08-non-goals.md](../08-non-goals.md) §3).

**Rejected — and this is the important one: automatic dispatch.** Not on a schedule, not when a
rate limit lifts, not when an agent goes idle, not when a tracker has an unassigned ticket. Every
one of those is wanted, several are written down in the inbox, and each is a *rule that decides
when to start work* — which is the queue [08-non-goals.md](../08-non-goals.md) §2 refuses and the
judgement this tool cannot see enough to have. If it is ever wanted, it is the next ADR, and it
needs an argument about what happens when the rule is wrong at three in the morning. This one does
not authorise it.

## How it is enforced

The import-graph test, again, and it is now three doors wide: `peer.py`, `tracker/` and
`dispatch.py`. A second test asserts that neither dangerous-permission flag appears in any
command this program builds — the shape of that check is a string search over the argument list,
which is crude and exactly right for a rule that must never be true.
