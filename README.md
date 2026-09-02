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
| [`docs/09-roadmap.md`](docs/09-roadmap.md) | four phases, each with a done-when criterion |
| [`docs/adr/`](docs/adr/) | the decisions, with their alternatives and costs |
| [`design/`](design/) | module layout and data model |

`docs/` says what must be true. `design/` says how. Present tense in either is a requirement on
the implementation, not a description of running code.

## Quickstart

```bash
make install          # dependencies, dev group included
make gate             # ruff · mypy · pytest -m unit
make run              # the console on http://127.0.0.1:8787
make overlay          # the same page in its own always-on-top window
```

Nothing here needs a server, a database daemon, a container or a network. One process, one SQLite
file under `~/.local/share/agent-desk/`, and read access to `~/.claude/`.

## Status

Specification and harness only. No implementation yet — [`docs/09-roadmap.md`](docs/09-roadmap.md)
lists Phase 1 in the order it should be built.
