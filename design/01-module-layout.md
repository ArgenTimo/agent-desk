# Module layout

```
agent_desk/
  observe/       the only module that parses what Claude Code writes to disk
    registry.py    ~/.claude/sessions/*.json  ·  liveness via pid + procStart
    transcript.py  tail of ~/.claude/projects/*/<sessionId>.jsonl
    jobs.py        ~/.claude/jobs/<short>/state.json — the one place that says done or failed
    shape.py       which repository a checkout belongs to — a worktree's pointer, a git config
    folder.py      a folder read one level: names, kinds, sizes. Never opens a file.
    attach.py      a folder or a remote resolved to a repository key
    signals.py     hook posts arriving at /api/signal
    model.py       Session, TranscriptTail, JobEnd, AgentCall — the types everything else sees

  store/         SQLite. Every SQL statement in the program is here, and redaction is at
    schema.sql     the boundary rather than in a template.
    NNN-*.sql      one file per change, applied in order at startup (see 02-data-model.md)
    repo.py        the queries, and the models the rest of the program passes around
    redact.py      applies .claude/security-patterns.yaml before text leaves the store

  answer/        one headless `claude -p` run per block
    session.py     subprocess, stream-json parsing, cancellation, timeout, a second engine
    classify.py    what a message is, which chat it belongs to, which ideas it is about

  ideas/         the pool: capture, reading, drafting
    inbox.py       capture — no model call, cannot fail on a busy machine
    appraise.py    what a background pass makes of an idea; never writes `state`
    describe.py    the one sentence a card says about itself
    meeting.py     a transcript read into the pool (docs/10)
    waking.py      when a deferred thing comes back — pure (031)
    kin.py  bench.py  chart.py    what belongs with what, and where it is drawn

  tracker/       somebody else's board, read and never written past one door
    jira.py        the board, its tickets, and the one door out (adr/0005, adr/0010)
    github.py      pull requests waiting on a person

  web/           FastAPI, Jinja2, HTMX, SSE. The only module that may dispatch or land.
    app.py         the lifespan: one task group, five loops, cancelled on the way out
    routes.py      every route
    blocks.py      the input field: one task group for every run in flight
    autostart.py   the queue loop — decides *when*, never *what* (adr/0007)
    kicking.py     the loop that will not let a switched-on session idle (adr/0009)
    later.py       the loop that brings back what was put off (031)
    engine.py      the loop that walks a drawing, one step at a time (037, adr/0011)
    blockers.py    what is stopped, computed rather than stored
    plans.py       what a session's tokens are spent against
    shared.py      a SECOND application: the ideas list, on its own bind, for a named viewer
    origin.py      refuses a state-changing request that a foreign page caused
    sse.py         the stream the board listens on

  the constructor — the vocabulary the workbench is built on (adr/0011). Pure, at the top
  level, because nothing in it belongs to the web or to the store:
    roles.py       Object · Action · Decision · Event · Result, and what each is asked (033, 035)
    ties.py        then · if · when · makes · with (034)
    process.py     a bench read as a process: the order, what feeds what, what a step is told
    allowed.py     what a step may do, and which of those this program actually enforces (036)
    telling.py     a drawing said in words, and words read back as a drawing

  dispatch.py    starting an agent: the argv, the briefing, the worktree name
  land.py        offering a branch to the project's own gate (adr/0008)
  peer.py        the ONE write path into a running session (adr/0002)
  connectors.py  what each kind of link lets this console actually do
  secrets.py     names an environment variable; never reads a credential file
  config.py      paths and settings, resolved once
  __main__.py    serves the console, and the shared view beside it when one is asked for
```

## Dependency direction

```
web  →  ideas  →  store  →  observe
 │        │                    ↑
 │        └──→  roles/ties/process/allowed/telling   (pure; import nothing but each other)
 │
 ├──→  answer  ───────────────┘
 ├──→  tracker
 └──→  dispatch · land · peer          (web only — see below)
```

Downward only. `observe` imports nothing from this package but `config` and `model`; it is
replaceable by a different source of sessions without anything else noticing.

The five constructor modules import `roles` and each other and nothing else — no store, no clock,
no subprocess. That is not tidiness: an engine whose ordering can only be observed by running
agents is an engine nobody can test, and `process.order` is asserted against a drawing rather
than against a machine.

## The rules that are tests

Four structural invariants are asserted in `tests/unit/test_structure.py` and
`tests/unit/test_security_surface.py`, against the syntax tree rather than the source text —
a substring search matches the comment explaining why a module does *not* do a thing:

- **only `observe/` parses what Claude Code writes** (adr/0004). `store/repo.py`,
  `answer/session.py`, `tracker/jira.py`, `tracker/github.py` and `secrets.py` are named
  exceptions, each because it parses JSON that is this program's own or somebody else's API.
- **only `web/` imports `dispatch`, `land`, `tracker` or `peer`** — the four doors out.
- **only `tracker/` opens a socket**, and every request it makes is https.
- **nothing reads a credential file.** The paths are named in `.claude/settings.json`'s deny
  list; the test is the second lock.
