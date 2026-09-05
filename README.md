# agent-desk

A read-first console for a developer running several Claude Code agents at once.

It answers, without touching a running session: **who is working on what, who is waiting for me,
and where do I put the idea I just had.**

```
~/.claude/sessions/*.json   ─┐
~/.claude/projects/**/*.jsonl ├─→  agent-desk  ─→  a page that hangs over the work
Stop / Notification hooks   ─┘        │
                                      └─→  an idea inbox that nobody's context pays for
```

## Why it exists

Five things break when two or more agents run in parallel, and none of them is a coding problem:

1. Watching consoles is a full-time job.
2. Asking an agent for its status costs the agent its context and costs you its momentum.
3. Ideas arrive mid-run; writing them into the running conversation is how a run loses the thread.
4. The developer falls out of context and no longer knows which request to send next.
5. People who do not write code want to contribute ideas and see progress.

[`docs/01-vision.md`](docs/01-vision.md) states these as requirements. The one that shapes
everything else is (2): **reading a session costs nothing, writing to one costs context.** So this
tool reads always and writes almost never, and the idea inbox exists precisely so that a thought
can be captured without any agent paying for it.

## What it is not

Not an orchestrator. It does not start, stop, steer or supervise your interactive sessions, and it
has no opinion about what they should do next. It is a window and a notebook.
[`docs/08-non-goals.md`](docs/08-non-goals.md) is the list, each entry with its reason.

## Documentation

| Read | For |
|---|---|
| [`docs/README.md`](docs/README.md) | the map |
| [`docs/01-vision.md`](docs/01-vision.md) | the problem, and what "solved" means |
| [`docs/02-architecture.md`](docs/02-architecture.md) | the components and what flows between them |
| [`docs/03-session-observation.md`](docs/03-session-observation.md) | the mechanism — the registry, the transcripts, the hooks |
| [`docs/04-threads-and-blocks.md`](docs/04-threads-and-blocks.md) | the non-blocking interaction model |
| [`docs/05-ideas.md`](docs/05-ideas.md) | capture, cards, and the one dangerous button |
| [`docs/06-console.md`](docs/06-console.md) | the screens and the overlay |
| [`docs/07-security.md`](docs/07-security.md) | transcripts hold secrets; this is what follows |
| [`docs/08-non-goals.md`](docs/08-non-goals.md) | what v1 deliberately does not do |
| [`docs/09-roadmap.md`](docs/09-roadmap.md) | five phases, each with a done-when criterion |
| [`docs/10-meeting-intake.md`](docs/10-meeting-intake.md) | what comes after v1, and why the hand-raise is not a new principle |
| [`docs/adr/`](docs/adr/) | the decisions, with their alternatives and costs |
| [`design/`](design/) | module layout and data model |

`docs/` says what must be true. `design/` says how. Present tense in either is a requirement on
the implementation, not a description of running code.

## Quickstart

```bash
make install          # dependencies, dev group included
make gate             # ruff · mypy · pytest -m unit
make run              # the console on http://127.0.0.1:8787
make share SHARE_HOST=192.168.1.10   # the console, plus the shared ideas list on the network
make overlay          # the same page in its own always-on-top window
```

Nothing here needs a server, a database daemon, a container or a network. One process, one SQLite
file under `~/.local/share/agent-desk/`, and read access to `~/.claude/`.

## Using it with your projects

**There is nothing to connect.** This is the part that is easy to miss, so it is worth stating
plainly: agent-desk is not installed *into* a project and is not configured *per* project. It reads
`~/.claude/`, which is where the CLI already records every session on this machine — so every
repository you run `claude` in appears on the board by itself, the first time it appears there.

That means the whole of "adding a project" is:

```bash
cd ~/wherever/the-project && claude      # you were going to do this anyway
```

and it is on the board. Nothing is written into that repository, ever — not a config file, not a
`.gitignore` line, not a directory (CLAUDE.md, rule two). A project you have not run anything in
yet can still be *declared* from the board (`+ new project`) so that ideas and links can hang off
it before there is a session.

What is optional, per project, and set from the board rather than from a file:

| On the project's page | What it does |
|---|---|
| **What should anybody working here know?** | prose handed verbatim to every agent this console starts here |
| **Words used here** | your names for things, so an agent is told what they mean |
| **Links** | Jira, GitHub, a dashboard — opened from the card's `⋯` menu |
| **Environment** | the *names* of variables the work needs; never a value ([`docs/07-security.md`](docs/07-security.md)) |
| **Start what I queue** / **find something to fix** | the two switches of [`adr/0007`](docs/adr/0007-a-loop-that-decides-when-not-what.md) and [`adr/0008`](docs/adr/0008-an-agent-that-finds-its-own-work.md) |

### On another machine

Same three lines. The database is per machine and holds this machine's ideas and settings; nothing
in it is shared, and nothing needs to be. The one file that has to travel with an installed copy —
the secret shapes the store redacts with — ships inside the package, and `make check-patterns`
fails if it drifts from the one the commit hook reads.

## Status

**Phases 1 and 2 are built. Neither is done. Phase 3 is built up to a wall. Phase 4 is built and
off by default.** The board reads the registry and the transcript
tails and pushes itself over server-sent events; the input field accepts a line and frees itself
immediately; blocks answer on their own time through a headless `claude -p` that cannot write
anywhere; ideas are captured before anything is generated and grow into drafts that stay in this
program's store; and a classifier proposes a subject that one click undoes
([`docs/09-roadmap.md`](docs/09-roadmap.md)).

The distinction is the one that page insists on: **a phase is not done because its tests pass.**
Phase 1's criterion is a full working day with three or more sessions in which every "what is that
agent doing" is answered from the board and no terminal is opened to check. Phase 2's is an idea
captured mid-run in under ten seconds, still legible a week later with what was happening around
it. Neither day has happened yet, and the count of times the board failed is the Phase 1 report.

Phase 4 puts an ideas list on the network for a named teammate, and it is the one thing here that
changes the security model — so it is served only when someone types `make share SHARE_HOST=…`.
It is a **second application on a second bind** that imports neither the session reader nor the
write path, so it cannot show a board or reach a session however it is called. A viewer gets a
long link of their own, stored hashed and shown once, revocable, and logged by name on every open.
The page shows an idea's summary, text, state and date — and nothing about the project, branch,
session or drafts it came from ([`docs/07-security.md`](docs/07-security.md)).

Phase 3 is the one path that can write to a running session. Its human half exists — the button,
the panel, the message shown in full beside the session it would reach — and the send reports
`needs_toolchain`, because the installed CLI publishes no client for its cross-session socket and
guessing that protocol would put a malformed prompt into somebody's working context. The panel
hands the text back to be pasted instead ([`docs/09-roadmap.md`](docs/09-roadmap.md)).

Six things a reader of the code should know before trusting it:

- The live CLI writes a status value this specification did not record — `waiting`, at `2.1.259`.
  The board shows the word and concludes nothing from it, and
  [`docs/03-session-observation.md`](docs/03-session-observation.md) records the observation. What
  it means is a human's call, not the reader's.
- **`agent_desk/web/static/htmx.min.js` is not in the repository** and is not fetched at runtime.
  Nothing depends on it: every action is a real form with a real action, and the routes answer a
  fragment to htmx and a whole page to a browser. Drop the file in and the page stops reloading
  on every click; leave it out and the console still works, it just blinks.
- Answering a block runs the `claude` CLI, which costs whatever your account charges. Nothing runs
  it on a timer: a block runs because a line was typed, and the classifier runs once per line
  when there are open subjects to classify against.
- The shared view has no TLS. The link travels in clear over whatever network it is served on,
  so it belongs on a trusted LAN or behind a tunnel, and not on the open internet.
- `agent_desk/peer.py` opens nothing — no file, no socket, no subprocess — and a test asserts
  that by reading its imports. It is the only module that could ever write to a session, and only
  `web/` may import it.
- The correction rate of the classifier is emitted as a log line on every override, not stored as
  a metric. Above roughly one in four, [`docs/04-threads-and-blocks.md`](docs/04-threads-and-blocks.md)
  says the classifier should be replaced by a default and a click.
