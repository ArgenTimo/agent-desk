# Module layout

```
agent_desk/
  observe/       the only module that parses what Claude Code writes to disk
    registry.py    ~/.claude/sessions/*.json  ·  liveness via pid + procStart
    transcript.py  tail of ~/.claude/projects/*/<sessionId>.jsonl
    signals.py     hook posts arriving at /api/signal
    model.py       Session, TranscriptTail, Signal — the types everything downstream sees
  store/         SQLite: threads, blocks, ideas, drafts  ·  redaction at this boundary
    schema.sql     tables, applied in order at startup
    repo.py        every SQL statement in the program lives here
    redact.py      applies .claude/security-patterns.yaml before text leaves the store
  answer/        one headless `claude -p` run per block
    session.py     subprocess, stream-json parsing, cancellation, timeout
    classify.py    new thread or continuation
  ideas/         capture, the card, the three draft actions
  web/           FastAPI app, Jinja2 templates, HTMX (from Phase 2), SSE
    app.py  routes.py  sse.py  templates/  static/
    blocks.py      the input field: one task group for every run in flight
    shared.py      a SECOND application: the ideas list, on its own bind, for a named viewer
  __main__.py    serves the console, and the shared view beside it when one is asked for
  peer.py        the ONE write path: a message to a named session
  config.py      paths and settings, resolved once
```

## Dependency direction

```
web  →  ideas  →  store  →  observe
 │                   ↑
 └──→  answer  ──────┘
 └──→  peer.py            (web only — see below)
```

Downward only. `observe` imports nothing from this package but `config` and `model`; it is
replaceable by a different source of sessions without anything else noticing.

## The two structural rules, each with a test

**1. Only `observe/` parses the on-disk formats.** No other module receives a raw line or a raw
dict from those files. Enforced by a test that greps the tree for `.claude/sessions`,
`.claude/projects` and `json.loads` outside `observe/`
([`../docs/adr/0004`](../docs/adr/0004-the-transcript-format-is-not-a-contract.md)).

`json.loads` is a proxy for "reads one of *those* formats", and it has two named exceptions, both
paths rather than categories. `store/repo.py` serialises `idea.context`, a JSON column in this
program's own SQLite file required by name in [`02-data-model.md`](02-data-model.md).
`answer/session.py` reads the stream-json of a subprocess this program started, which is this
line's own description of that module's job. Any third module that starts parsing JSON still fails
the test, which is the point of keeping the exceptions as a list of paths.

**1a. `web/shared.py` imports neither `observe` nor `peer`.** It is the surface a second person
can open, and the guarantee that it cannot show a board or reach a session is an import graph
rather than a branch ([`../docs/07-security.md`](../docs/07-security.md), Phase 4).

**2. Only `web/` imports `peer.py`.** The write path exists in exactly one place, behind a route a
human reaches by clicking. Enforced by an import-graph test asserting that `observe`, `store`,
`answer` and `ideas` do not import it — the mechanism behind
[`../docs/adr/0002`](../docs/adr/0002-read-first-never-interrupt.md).

A third rule is worth stating even though it needs no test, because it is the one a hurried
afternoon breaks: **`observe/` opens files for reading and never for writing.** Its whole
correctness claim is that the observed session cannot tell it ran.

## Where SQL lives

`store/repo.py`, and nowhere else. `schema.sql` is schema, not a query. The reason is the same one
that makes `observe/` a single module: one place to look when the storage shape changes.

## Tests

```
tests/
  unit/        markers: unit  — everything, since nothing here needs a service
  fixtures/    recorded registry entries and transcript lines, with the CLI version
```

`make gate` runs ruff, mypy and `pytest -m unit`. There is no integration marker yet and adding one
should be resisted: a local tool whose only external dependency is the filesystem does not need a
second suite, it needs fakes over a `tmp_path`
([`.claude/skills/fakes-over-mocks`](../.claude/skills/fakes-over-mocks/SKILL.md)).
