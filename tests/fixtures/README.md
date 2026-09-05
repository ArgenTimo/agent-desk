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
| `registry_entry_headless.json` | `~/.claude/sessions/<pid>.json` of a `claude -p` run | `2.1.259` |
| `stream_json.jsonl` | stdout of `claude --print --output-format stream-json` | `2.1.259` |
| `job_state_failed.json` | `~/.claude/jobs/<short>/state.json` of a `--bg` job that died | `2.1.261` |
| `job_state_done.json` | `~/.claude/jobs/<short>/state.json` of a `--bg` job that worked | `2.1.261` |

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

## The entry this tool creates by working

`registry_entry_headless.json` was recorded from a headless `claude -p` that agent-desk itself
started, caught while it lived — the CLI removes the file the moment the run ends, which is why
the first attempt to record it found nothing.

It is in here because it was found the hard way. The board raised two red banners during the first
end-to-end run, naming three missing fields, and the entries they named were this program's own
answer runs: `entrypoint` is `sdk-cli` rather than `cli`, and a headless run publishes no `status`
because nothing is watching it work. `kind` says `interactive` in both, so the obvious
discriminator is the wrong one.

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

## The two files that say how a dispatched agent ended

`job_state_failed.json` and `job_state_done.json` are the same shape twice, and the pair is the
point: the registry says only whether a session is alive, so the *difference* between an agent
that worked all night and one that exited in a second is here or nowhere.

They were recorded the hard way too. Six agents dispatched from the console died on
`Error creating worktree: Invalid worktree name "берём-в-работу"` — the CLI accepts only ASCII
letters, digits, dots, underscores and dashes, and `str.isalnum` is true for every alphabet. The
console reported all six as finished work and marked the ideas they carried as built, because
"gone from the registry" was the only fact it was reading. `agent_desk/observe/jobs.py` reads the
other one.

The failed file carries no `worktreeBranch`, `tokens` or `name` at all — it never got far enough
to have them — which is why those are optional in the model rather than merely unread. The done
one carries `worktreeBranch`, and it is preferred over re-deriving the slug: the branch the CLI
actually made is a fact, and a second derivation is a second copy of its rules to keep in step.
