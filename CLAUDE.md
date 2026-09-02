# CLAUDE.md

`agent-desk` — a read-first console over the Claude Code sessions running on this machine, plus an
idea inbox that costs no agent any context.

Read [`docs/01-vision.md`](docs/01-vision.md) before adding anything that talks to a session,
and [`docs/03-session-observation.md`](docs/03-session-observation.md) before touching anything
that parses what Claude Code writes to disk.

## 1. Think before coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State assumptions explicitly. If uncertain, ask.
- If several interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.

## 2. Simplicity first

This is a local single-user tool. One process, one SQLite file, no build step, no container, no
daemon. The minimum that solves the problem: no abstractions for single-use code, no
configurability nobody requested, no error handling for impossible states. If you wrote 200 lines
and it could be 50, rewrite it.

The pull toward turning this into a second ai-worker is strong and must be resisted. It has no
tickets, no lifecycle, no approvals, no clients, and no multi-tenancy.

## 3. Surgical changes

Touch only what you must. Don't improve adjacent code, don't reformat, don't refactor what isn't
broken. Every changed line traces to the task.

## 4. Goal-driven execution

Turn tasks into verifiable goals with success criteria, and loop until verified. For multi-step
work, state a brief plan with a check per step.

---

# The five rules that are not negotiable

```
✗ write into a running session's context without an explicit human click
✗ write anything at all into an observed repository or its worktree
✗ read a credential — ~/.claude/.credentials.json, ~/.claude/sessions/*.key, any .env
✗ show a transcript excerpt to a non-privileged viewer unredacted
✗ report a status as known when it was inferred from silence
```

Each one has a reason, and the reason is in a document:

**Writing costs context.** Reading `~/.claude/` is free and invisible to the agent being read.
Sending a message is not: it lands in that session's context window and displaces work. The whole
value proposition collapses if this tool becomes another source of interruption, so a message to a
session is a deliberate human act with a button behind it, never a side effect of a background
loop ([`docs/adr/0002`](docs/adr/0002-read-first-never-interrupt.md)).

**This tool is a reader of other repositories, never a writer.** An idea that should become
documentation produces a *draft proposal in agent-desk's own store*, which a human then carries
into the target repository through the normal review path. A tool that edits a spec on the
strength of a chat message is the failure `docs/17-deferred.md` §18 in the ai-worker repository
describes ([`docs/05-ideas.md`](docs/05-ideas.md)).

**Credentials.** `~/.claude/sessions/*.key` authenticates the peer-messaging socket and
`.credentials.json` holds the account token. Neither is ever opened, logged, or passed to a
subprocess. `.claude/settings.json` denies them; that denial is the mechanism, this paragraph is
only the explanation ([`docs/07-security.md`](docs/07-security.md)).

**Transcripts hold everything the agent saw** — source, tokens pasted by a human, output of
commands. Any surface that a second person can open redacts before it renders, and redaction runs
at the store boundary rather than in the template ([`docs/07-security.md`](docs/07-security.md)).

**Unknown has a name.** `idle`, `busy` and `shell` come from the registry and are facts. "Waiting
for a human" is *not* in the registry and cannot be derived from a transcript with certainty — it
is an inference from silence, and it is rendered as an inference. A guessed status is worse than
no status, because the whole point of the tool is that you can trust the board without opening a
terminal ([`docs/03-session-observation.md`](docs/03-session-observation.md)).

## The format is not a contract

`~/.claude/sessions/*.json` and `~/.claude/projects/**/*.jsonl` are Claude Code's internal state.
Nobody promised they are stable, and a CLI update may change them without warning.

So: **one parser module, fixtures recorded from real files, and a version check.** Every shape
this code depends on is captured in `tests/fixtures/` with the `version` field of the CLI that
produced it. When the format moves, one module fails loudly with a message naming what changed —
instead of five call sites quietly reading `None`
([`docs/adr/0004`](docs/adr/0004-the-transcript-format-is-not-a-contract.md)).

Never parse those files anywhere but `agent_desk/observe/`.

## Stack

Python 3.12 · asyncio · FastAPI · SQLAlchemy 2.0 async over SQLite · Jinja2 + HTMX + SSE ·
pytest · ruff · mypy. Headless `claude -p --output-format stream-json` as the answer engine.

**No JavaScript build step.** The console is server-rendered with HTMX and server-sent events. A
local tool that needs `npm install` before it can show you a list of five sessions has lost the
argument ([`docs/adr/0003`](docs/adr/0003-sqlite-and-one-process.md)).

Every gate is a `make` target — use them rather than composing the underlying command, so that
what you ran and what the Stop hook runs are the same thing:

```
make install   dependencies, dev group included
make gate      ruff · mypy · pytest -m unit     — what stop-verify.sh runs at every turn end
make verify    gate + check-links
make run       the console
```

Two async mistakes that hurt most here: blocking IO in an async path stalls the whole console, and
a fire-and-forget `create_task` produces a failure nobody observes. Use `TaskGroup`.

## Working conventions

**One worktree per task**, off a fresh `origin/main`:

```
git worktree add ../agent-desk-<slug> -b <slug> origin/main
```

`<slug>` is two or three words describing the task — `registry-reader`, `idea-card`. There is no
tracker here, so the slug takes the place of the ticket key the `worktree-workflow` skill expects,
and `branch_prefix` is empty in the profile for the same reason. The Stop hooks lint the tree the
session is in, which is why a shared checkout makes their output ambiguous.

**Tests ship with the change.** A parser without a recorded fixture and a store write without a
crash case are incomplete.

**Draft-first pull requests.** `gh pr create --draft`, un-draft at the end.

**Commit messages name the document the change serves:**

```
observe: verify a registry entry against procStart before trusting its pid

docs/03-session-observation.md requires a liveness check that survives pid reuse;
the previous reader trusted the file and would have shown a dead session as busy.
```

## The skillset

`.claude/` came from `project-template/` in the ai-worker repository and is the same skillset that
repository installs into every project it manages — 36 skills indexed in
[`.claude/skills/README.md`](.claude/skills/README.md), five hooks, and one profile file that
every skill reads.

Two consequences worth knowing before you edit any of it:

- **`.claude/.ai-worker/project-profile.yml` is the only place project facts live.** Every skill
  and hook resolves commands from it; none hardcodes a path. If a command changes, it changes
  there and nowhere else.
- **The directory is still called `.ai-worker/`** even though this is not that project. The name
  is the contract path five hooks and 36 skills read. Renaming it forks the template for the sake
  of a word, and the next improvement upstream would no longer apply here.

Some skills do not apply to this repository and say so in
[`.claude/.ai-worker/capabilities.yml`](.claude/.ai-worker/capabilities.yml) — a skill marked
`not_applicable` reports that rather than inventing work. Marked so far: everything that assumes
a tracker, a client project, or a CI pipeline this repository does not have.

## When a gate is red

A red gate is not a reason to summarise progress. It is the work that is left.
