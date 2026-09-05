# Non-goals

What v1 does not do, and what would have to be true for each to change. Each entry names the
assumption to test, so that adding it later is a decision with evidence rather than an itch.

## 1. Orchestrating sessions

No **steering** of interactive sessions: nothing written into a running context, no keystrokes, no
stopping somebody else's terminal. The board watches the sessions it did not start.

**Why:** a tool that changes the work needs to be trusted like the thing doing the work — audit,
identity, permissions. **Entry condition:** never, in this program. If it is wanted, it is a
different one ([adr/0001](adr/0001-a-separate-repository.md)).

**Narrowed three times, and the ADRs carry the argument.** The console may *start* a background agent in
a worktree of its own when a human clicks ([adr/0006](adr/0006-the-desk-may-start-work.md)), and a
loop may decide *when* to start something a human already queued
([adr/0007](adr/0007-a-loop-that-decides-when-not-what.md)), and a project switched on for it may
send one agent to *find* something worth fixing when its queue is empty
([adr/0008](adr/0008-an-agent-that-finds-its-own-work.md)) — fixing, never designing, everything it
produces marked as its own, and never merged. All three are about work this program creates and
can stop. None of them touches a session somebody else is sitting in, which is what this section
was written to protect.

## 2. Sending work to a busy session

The one write path is a human clicking send on a message to a named session
([adr/0002](adr/0002-read-first-never-interrupt.md)). There is no queue that delivers a batch when
a session goes idle, and no rule that decides a good moment.

**Why:** "a good moment" is a judgement about work this tool cannot see the inside of.
**Assumption to test:** count how often a captured idea is later pasted into a session by hand. If
it is most of them, and always at the same moment — the session going idle — a hold-and-offer queue
has evidence behind it.

**Still true for a session that is already running**, and that is the whole of what this section
is about. [adr/0007](adr/0007-a-loop-that-decides-when-not-what.md) allows a queue whose items are
started as *new* agents — the judgement it makes is when to start work somebody approved, never
when to interrupt work somebody is doing.

## 3. `tmux send-keys` into a terminal

Typing into somebody else's terminal is available, cheap, and wrong. It is an interruption wearing
an automation costume, and it lands in the middle of whatever was being typed.

**Why:** it converts this tool from an observer into the loudest source of the problem it exists to
solve. **Entry condition:** none.

## 4. A backlog

Ideas have four states and no priority, assignee, estimate, or ordering
([05-ideas.md](05-ideas.md)).

**Why:** a backlog needs a process to stay honest, and an untended one is worse than a notebook
because it looks like a plan. **Assumption to test:** if the inbox regularly exceeds ~50 kept ideas
and promotion still happens, ordering is earning its keep.

## 5. Writing into an observed repository

Promotion produces drafts in this tool's own store. Nothing opens a pull request or files a ticket
([05-ideas.md](05-ideas.md)).

**Why:** the review between an idea and a written artefact is the part that makes the artefact worth
reading. **Entry condition:** an ADR, not a commit.

## 6. Multi-user access

One operating-system user, loopback only, no authentication
([07-security.md](07-security.md)).

**Why:** anything that can reach the port can already read `~/.claude/`. **Entry condition:** the
Phase 3 criterion of [09-roadmap.md](09-roadmap.md) — a teammate has actually asked twice, and the
redacted ideas view exists.

## 7. A desktop application

The overlay is a browser window with a window rule, not Electron or Tauri
([06-console.md](06-console.md)).

**Why:** several days of packaging to render the same HTML. **Assumption to test:** whether the
window rule survives daily use across restarts and workspace switches. If it needs fixing weekly, a
wrapper is cheaper than the annoyance.

## 8. Reading anything but Claude Code sessions

No git log ingestion, no CI status, no tracker, no editor state.

**Why:** each is a second integration with its own failure mode, and none of them answers "what is
the agent doing right now", which is the question. **Assumption to test:** which question the board
fails to answer most often. If it is "did that branch land", git is the next source — and it is
local, read-only, and cheap.

## 9. Transcript search, diff views, tool-call browsing

A row expands to a tail. That is the drill-down.

**Why:** the terminal that has the session is already open and better at this.
**Assumption to test:** how often expanding the tail is followed by switching to the terminal
anyway. If it is rare, the tail is enough; if it is always, the board is missing the thing that
would have answered the question.


## Routing around a refusal

One idea in the pool asks for local models to be integrated so that a request can be **re-sent to a
local model when Claude declines to answer on ethical grounds**.

The first half is ordinary and may well get built one day: running a cheap local model for the
small classifications this console makes all the time — what kind of line was typed, which ideas a
request touches — would cost nothing per call and would keep working when the network does not.
Routing on *availability* is the same kind of decision as any other fallback.

The second half is not, and it is not a matter of degree. A refusal is an answer. Machinery whose
purpose is to take a request that was declined and put it somewhere that will not decline it is
machinery for getting around the judgement rather than for getting an answer — and it does not
become something else because it is built into a tool that mostly does other things. It is not
built here and it will not be.

Nothing about that limits the useful half. Availability routing — a rate limit, an outage, a model
that is simply slower than the job needs — is a different trigger with a different reason, and it
is welcome whenever somebody wants it enough to run a local model to test it against.
