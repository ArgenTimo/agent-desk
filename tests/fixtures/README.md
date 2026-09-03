# Fixtures

Recorded from real files on a real machine, then scrubbed. Not written by hand.

That distinction is the whole point of
[`docs/adr/0004`](../../docs/adr/0004-the-transcript-format-is-not-a-contract.md): a hand-written
fixture encodes what its author *believed* the format was, and it keeps passing after the real
format has moved. A recorded one fails, with a name attached, on the day the CLI changes.

| File | Recorded from | CLI `version` |
|---|---|---|
| `registry_entry.json` | `~/.claude/sessions/<pid>.json` | `2.1.259` |
| `transcript.jsonl` | `~/.claude/projects/<slug>/<sessionId>.jsonl` | `2.1.258` |
| `stream_json.jsonl` | stdout of `claude --print --output-format stream-json` | `2.1.259` |

## What was scrubbed, and what was not

**Structure is untouched.** Every key, every nesting level, every type is as it was found — that is
the thing under test.

**Identifiers and content are replaced.** Session ids, the machine id inside `pidDomain`, the
bridge session id, paths, and every piece of message text. A transcript holds source code, command
output, and anything a human pasted, so a fixture keeps its shape and loses its content
([`docs/07-security.md`](../../docs/07-security.md)).

`transcript.jsonl` covers the six line types v1 cares about, including one `isSidechain: true`
entry that the reader must skip.

## Re-recording

When a CLI update breaks a parser test, re-record rather than patch:

1. Copy a real file from `~/.claude/`.
2. Replace identifiers and every piece of text content, keeping structure exactly.
3. Update the `version` column above, and the version noted in
   [`docs/03-session-observation.md`](../../docs/03-session-observation.md).

This is a normal task with a normal review, not an emergency.

## The stream is a format too

`stream_json.jsonl` is the stdout of one real headless run — the answer engine's input, recorded
the same way and for the same reason as the two files above. It is what the parser in
`agent_desk/answer/session.py` is tested against, and the test's fake `claude` is a script that
prints this file: the shapes the parser depends on come from a run that happened, not from a
reading of the help text.

It cost one request. The run that produced it carried a `rate_limit_event` line — a type v1 does
not read and skips — which is the whole argument for recording rather than writing: nobody would
have invented that line, and a parser that fell over on an unknown `type` would have looked
correct until the day it met one.

## Two notes from the second recording

`registry_entry.json` was re-recorded at `2.1.259`. The key set and every type were **identical**
to the `2.1.258` recording — the update that moved the version moved nothing this program reads.
That is worth writing down: the check is cheap precisely because most of the time it says nothing
changed, and the one time it says otherwise is the day it earns its keep.

**One shape is documented and not recorded.** `docs/03-session-observation.md` records a fourth
status value, `waiting`, seen in the registry at `2.1.259`. No live session carried it at the
moment this fixture was re-recorded, and a fixture is recorded rather than written — inventing the
entry would produce exactly the hand-written artefact
[`docs/adr/0004`](../../docs/adr/0004-the-transcript-format-is-not-a-contract.md) exists to
replace. The value is covered by an ordering test instead, and the gap is named here rather than
papered over. Re-record when a session is next seen holding it.

## A note recorded on the first day

These fixtures were captured at `2.1.251` and re-recorded at `2.1.258` within the same afternoon,
because the CLI updated itself in between. A new key (`bridgeSessionId`) had appeared. Nothing
broke, and nothing announced it either — which is the argument for this directory, made by the
subject of it, before a line of the parser existed.
