# Session observation

Three sources, in decreasing order of how much you can trust them. All three are read without the
observed session noticing, which is the property the whole tool is built on
([adr/0002](adr/0002-read-first-never-interrupt.md)).

Everything on this page was verified against Claude Code `2.1.251` on Linux, re-checked at
`2.1.258` — the CLI updated itself between the two readings, and a key had appeared — and read
again at `2.1.259`, where the shape held and a status value did not. Nothing broke and nothing
announced it, which is [adr/0004](adr/0004-the-transcript-format-is-not-a-contract.md)
demonstrating its own argument before a line of the parser existed.

These files are internal state, not a published interface. Treat every shape below as *recorded*,
not *promised*.

## 1. The registry — `~/.claude/sessions/<pid>.json`

One file per live session, rewritten as the session's status changes, removed when it exits.

```json
{"pid": 15688,
 "sessionId": "…", "cwd": "/home/skotwind/PycharmProjects/llm-developer-2",
 "name": "llm-developer-2-d0", "nameSource": "derived",
 "kind": "interactive", "entrypoint": "cli", "version": "2.1.251",
 "status": "busy", "statusUpdatedAt": 1788378927405, "updatedAt": 1788378927405,
 "startedAt": 1788182708626, "procStart": "21170",
 "pidDomain": "linux:…:pid:[4026531836]",
 "messagingSocketPath": "/run/user/1000/cc-socks/15688.sock",
 "peerProtocol": 1, "peerFeatures": ["notify_idle", "…"]}
```

This is the board's backbone: it gives the name, the working directory, and a status, for every
session, for the cost of reading five small files.

**`status` is a fact and it is rendered as-is.** It is written by the session itself, and it is the
only trustworthy statement about what a session is doing. Three values were recorded at `2.1.251`
and `2.1.258` — `idle`, `busy`, `shell`.

**A fourth appeared.** On 2026-09-03, at CLI `2.1.259`, the registry on this machine carried
`waiting`. Nothing on disk says what the session means by it, so v1 does not act on it: the value
is shown as the session wrote it, and it is ordered below `busy` and above `idle` — not treated as
the "waiting for a human" fact that the rest of this page says cannot be known. Deciding that it
*is* that fact is a change to this document, made by a human who has confirmed the meaning; it is
not a change the reader may make on the strength of the word ([adr/0004](adr/0004-the-transcript-format-is-not-a-contract.md)).

**Not every entry is a session a human is working with.** A headless `claude -p` registers itself
in the same directory, with `entrypoint` naming the SDK that started it (`sdk-cli`, `sdk-py`)
rather than `cli`, and it publishes **no `status` at all** — nothing is watching it work. Note that
`kind` says `interactive` for both, so it is not the field that separates them.

The board skips those entries, and skips them *quietly*. They are not sessions to triage: they
appear and vanish with every question typed into this console, and one of them is this program
answering that question ([06-console.md](06-console.md)). Nor are they a format that moved — an
entry with no `status` is a different shape, not a broken one, and a banner that fires every time
the tool is used is a banner nobody reads
([adr/0004](adr/0004-the-transcript-format-is-not-a-contract.md)).

Recorded 2026-09-03 at `2.1.259`, and found by running the console against its own machine rather
than by reading the format: the first end-to-end run raised two red banners, and both were
agent-desk's own answer runs.

**A file is a claim about a process, and the claim is checkable.** A stale file, or a pid the
operating system has since handed to something else, would put a dead session on the board as
`busy` — the exact failure that makes a status board worthless. So liveness is two checks, not
one:

1. `/proc/<pid>` exists, and
2. field 22 (`starttime`) of `/proc/<pid>/stat` equals the `procStart` string in the file.

The second is what survives pid reuse, and it is why the field is in the file at all. A session
failing either check is not shown; it is not an error either, just a session that has ended.

**Never sort the board by `updatedAt` alone.** It moves when status moves, so a long, healthy,
uninterrupted run looks stale next to a session that flickered between `idle` and `busy` twice.
Sort by what the human is deciding: sessions wanting attention first ([06-console.md](06-console.md)).

## 2. The transcript — `~/.claude/projects/<slug>/<sessionId>.jsonl`

Append-only, one JSON object per line, written as the session works.

**Find it by globbing `~/.claude/projects/*/<sessionId>.jsonl`. Never derive `<slug>` from `cwd`.**
The slug is a lossy transform — `/home/skotwind/Project Zomboid My Mods` becomes
`-home-skotwind-Project-Zomboid-My-Mods`, with the separator and the spaces mapped to the same
character — so it cannot be inverted and two directories can collide in it. The session id is
unique and the glob is one syscall.

Line types recorded so far, with what each is good for:

| `type` | Carries | Used for |
|---|---|---|
| `ai-title` | `aiTitle` — a generated title for the session | **the headline on the board**: what this session is about, in five words |
| `last-prompt` | `lastPrompt` | the last thing the human asked |
| `user` | `message`, `cwd`, `gitBranch`, `timestamp` | the request stream, and the branch the work is on |
| `assistant` | `message` (content blocks, incl. tool calls), `requestId`, `timestamp` | the last action taken, and when |
| `attachment` | file and context attachments | ignored by v1 |
| `atis-latch`, `queue-operation` | internal bookkeeping | ignored by v1 |

Entries carry `uuid`/`parentUuid`, so the file is a tree rather than a list, and `isSidechain`
marks subagent work. v1 reads the main chain and ignores sidechains: a subagent's tool calls are
noise on a board whose job is to say what the *session* is doing.

**Read the tail, not the file.** These reach tens of megabytes. The board needs the last handful
of lines; seek from the end.

**`gitBranch` in a transcript entry is what makes the board make sense across worktrees**, where
several sessions share one repository name but not one branch.

## 3. Hook signals — `POST /api/signal`

The two sources above are pull. A `Stop` or `Notification` hook in an observed project is push,
and it is the only way to learn something at the instant it happens.

The hook posts session id, project, event, and nothing else — never a prompt, never a diff, never
output. See [07-security.md](07-security.md); a hook that ships transcript content into a second
store has doubled the redaction problem for the sake of latency.

Installing it in a watched project is optional. The board is complete without it and merely less
immediate.

## What cannot be known, and is therefore not claimed

**"This session is waiting for me."** Nothing on disk says it. `idle` means the session is not
currently working — which is also true of a session whose human walked away, and of one that
finished cleanly an hour ago.

It can be *inferred*: `idle`, plus a last transcript entry from the assistant, plus no change for
N seconds. That inference is useful and it is shown — as an inference, with the observation behind
it visible ("idle 14m, last entry assistant"), never as a bare claim that the agent is waiting.

The reliable version of this signal is the `Notification` hook, because the session raises it
itself. Where the hook is installed, the board says so; where it is not, the board says it is
guessing. Two words of honesty here are the difference between a board you trust at a glance and
one you verify in a terminal — and verifying it in a terminal is the problem this tool exists to
remove ([01-vision.md](01-vision.md), problem 1).

## Fixtures

Every shape above is recorded under `tests/fixtures/`, with the CLI `version` that produced it,
and the parser is tested against the recording rather than against a hand-written idea of it. When
a CLI update changes a shape, the fixture test fails with a name attached — which is the entire
plan for that day ([adr/0004](adr/0004-the-transcript-format-is-not-a-contract.md)).

**The version banner points forward.** A session reporting a version *newer* than the recording is
the case that ADR is about, and it is what the banner names. A session older than the recording
raises nothing: an older shape that no longer fits produces its own notice naming the field, which
is the specific signal, and sessions here live for days — so a banner lit by age alone would be lit
permanently, and a banner that is always on is one nobody reads. `tests/fixtures/README.md` records
one shape that is documented above and deliberately not recorded, and why.
