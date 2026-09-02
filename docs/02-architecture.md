# Architecture

One process. Four components. Data flows in one direction, and the arrow that does not exist is
the important one.

```
  ~/.claude/sessions/*.json ─────┐
  ~/.claude/projects/**/*.jsonl ─┼──→ observe ──→ store ──→ web ──→ browser (SSE)
  hooks POSTing to /api/signal ──┘                  ↑           │
                                                    │           │ human clicks
                                                 answer ←───────┘
                                                    │
                                              claude -p (headless)

  ✗ there is no arrow from any component back into an observed session,
    except the one a human click creates.
```

## observe

Reads the three sources of [03-session-observation.md](03-session-observation.md) and turns them
into rows. Polls the registry on a timer, tails the transcript of a session the console is
actually showing, and accepts hook signals pushed to it.

Entirely read-only towards the outside world. It opens files under `~/.claude/` and nothing else;
it never opens a file inside an observed repository, and it never writes one anywhere.

This is the only module allowed to know the on-disk formats. Everything downstream sees
`agent_desk` types ([`design/01-module-layout.md`](../design/01-module-layout.md)).

It is *a* source, not *the* source. A reader of meeting transcripts would be a sibling package
under the same rule — its own format stays inside it, it hands downstream the same types, and it is
read-only towards whatever produced its input ([`10-meeting-intake.md`](10-meeting-intake.md)).
Nothing is abstracted for that today; the sentence is the whole preparation.

## store

SQLite through async SQLAlchemy, one file under `~/.local/share/agent-desk/`. Holds what the tool
itself produces and must not lose: threads, blocks, ideas, and the drafts an idea grows into
([`design/02-data-model.md`](../design/02-data-model.md)).

It does **not** hold a copy of the transcripts. Those are large, they already exist on disk, and a
second copy is a second thing to redact ([07-security.md](07-security.md)). Session state is
projected fresh on read and cached in memory only.

Redaction runs here, at the boundary, rather than in a template. A view that forgets to call a
filter is a bug that renders correctly.

## answer

Runs `claude -p --output-format stream-json` for one block, streams its events, writes the result
back to that block. One subprocess per block, cancellable, with its own timeout.

Two things it deliberately is not: it is not a router (it does not decide which agent should do
the work) and it is not a resumer of somebody else's session (it starts its own, with its own
context). See [08-non-goals.md](08-non-goals.md).

## web

FastAPI, Jinja2 templates, HTMX for interaction, server-sent events for the live board. Bound to
`127.0.0.1` and to one operating-system user by default. The overlay is the same page in a
dedicated always-on-top browser window ([06-console.md](06-console.md)).

No JavaScript build step ([adr/0003](adr/0003-sqlite-and-one-process.md)).

## The arrow that does not exist

Nothing in `observe`, `store` or `answer` may open a socket to a running session. The single path
that can is one route in `web`, reached only by a human clicking a button that names the session
and shows the message before it goes ([adr/0002](adr/0002-read-first-never-interrupt.md)).

That is a structural rule, not a habit: `agent_desk/observe/` and `agent_desk/answer/` do not
import the peer-messaging client at all, and a test asserts it.

## Failure posture

Every source can be absent, and none of them being absent is an error worth stopping for:

| Missing | Consequence |
|---|---|
| `~/.claude/sessions/` empty | the board is empty and says "no live sessions", not an error |
| a transcript file unreadable | that session shows registry facts only, marked as such |
| the `claude` CLI absent | blocks queue and report `needs_toolchain`; the board still works |
| the store file locked | the board still renders; capture reports the failure to the human |

The board keeps working when the extras do not, because the board is the part that replaces
staring at terminals.
