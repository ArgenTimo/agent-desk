# Meeting intake

Beyond v1. Three versions, each a superset of the last, and one principle that already exists
carried into a room with people in it.

**1+ is built** (`agent_desk/ideas/meeting.py`): paste a transcript into the pool and it writes
down the ideas in it. 1++ and 1+++ are not, and both need something this machine does not have —
audio, and consent from a room.

This page was written before any of it existed, because two decisions taken then — where a
captured thing records **where it came from**, and where a second observation source plugs in —
were cheap at the time and expensive after a year of rows. `source_kind = "meeting"` is the first
of those two, and it was already in the store when the reader was written.

## The three versions

| Version | What it does | The new thing it needs |
|---|---|---|
| **1+** | reads a transcript of a meeting that already happened, and proposes idea blocks from it | a second source, and batch capture |
| **1++** | is present live, transcribing as the meeting runs | audio, and consent from everyone in the room |
| **1+++** | raises a hand, and asks its question aloud when called on — or, minimally, types it into the meeting chat | a turn, granted by a human |

## Why 1+++ is not a new principle

It looks like the biggest step and it is the smallest.

[`adr/0002`](adr/0002-read-first-never-interrupt.md) says: read always, write only when a human
clicks. The reason is that writing into a running session costs that session its context and
displaces the work in progress.

A meeting is the same structure with people instead of agents. Speaking into one costs every
person in it their attention, and it displaces whatever was being said. So the rule transfers
unchanged — and **raising a hand is exactly the click.** The agent asks for a turn; a human grants
it; only then does it speak. Not a workaround for a limitation: it is the same invariant, and it
happens to be how a well-behaved person behaves in a meeting too.

The minimal form — typing into the meeting chat — is the same thing at lower cost. A chat message
does not take the floor, so it needs no turn. Both are available; the loud one needs permission and
the quiet one does not.

What would violate the principle: speaking unprompted, interrupting, or a queue that decides a good
moment to talk. That is [`08-non-goals.md`](08-non-goals.md) §2 in a room, and the answer is the
same one.

## Consent, which is the real blocker

Version 1+ reads a transcript somebody else already made and already shared. That is ordinary.

Versions 1++ and 1+++ record and transcribe **other people**, and one of them speaks as an agent
among humans who may not know it is there. Three requirements, and none of them is negotiable by
an architecture decision:

- **Everyone in the meeting is told, before it starts, that this is running and what it keeps.**
  Not a line in a settings page; an announcement in the room.
- **Recording law is local and some of it is two-party consent.** Where the participants are, not
  where the laptop is.
- **A person's words are not an idea's provenance until they agree to it.** An idea captured from
  a meeting names the meeting; it names a person only where that person is a participant who knows
  the tool is running.

The engineering consequence: **1++ and 1+++ are gated on an explicit, per-meeting human action,
never on a setting that stays on.** A tool that silently joins the next call because it joined the
last one is the failure mode, and it is the one that ends the tool's life in an organisation.

Version 1+ has none of this weight, which is why it is version 1+ and the others are not.

## What the foundation does now

Two changes, both already made, both cheap only because nothing has been built on top of them yet.

**1. A captured thing records its source, not its session.** An idea's context was going to be
`project` / `branch` / `session_id` — three columns shaped like a Claude Code session, which is
one source of one kind. It is now `source_kind` plus `source_ref` plus a free `context` map
([`../design/02-data-model.md`](../design/02-data-model.md)). A meeting-sourced idea sets
`source_kind = "meeting"` and puts the meeting, the timestamp and the speaker in the map; nothing
in the store, the inbox or the drafts changes.

**2. `observe/` is named as *a* source, not *the* source.** Today it is the only one, and
[`adr/0004`](adr/0004-the-transcript-format-is-not-a-contract.md) keeps every on-disk format inside
it. A meeting reader is a sibling package under the same rule — it parses its own format, it hands
downstream the same types, and it is read-only towards whatever produced its input
([`02-architecture.md`](02-architecture.md)).

That is the whole investment. No interface is generalised, no plugin system exists, and no code was
written for a version that has no user yet — building the abstraction now would be
[`../CLAUDE.md`](../CLAUDE.md) rule 2 broken in the name of a roadmap.

## What batch capture will need, and does not have

An idea typed into the input field arrives one at a time, and the card asks one question: keep or
discard ([`05-ideas.md`](05-ideas.md)).

A one-hour meeting proposes twelve at once, and twelve cards is not twelve times one card — it is a
review queue, and a review queue that arrives at the end of a meeting is a chore nobody does. The
open question, recorded rather than answered: whether the right shape is one card per idea, one
digest with checkboxes, or a single "meeting notes" idea that a human splits later.

That is a design question for the day version 1+ has a real transcript in front of it. Guessing at
it now would produce an interface built against an imagined meeting.

## The sibling that already owns this

In the CTI suite that ai-worker belongs to, **Manager** owns meetings and turning call transcripts
into action points, and **Secretary** owns messaging between people and agents. If that suite is
ever deployed where this tool runs, meeting intake here is a personal-scale duplicate of a
sibling's job — the thing ai-worker's own `CLAUDE.md` forbids inside that repository.

It is not forbidden here, because agent-desk is deliberately a personal tool outside that suite
([`adr/0001`](adr/0001-a-separate-repository.md)) and a developer's own notebook is not a company's
meeting system. But the overlap is real and it is written down, so that the day someone proposes
wiring this into a shared deployment, the question "should this be Manager instead" is already on
the page rather than discovered afterwards.


## What 1+ actually does, and what it refuses

**It proposes; it does not decide.** Everything it finds arrives as an ordinary idea in the `new`
state, marked as having come from a meeting, and a person keeps or discards each one exactly as
they would a thought they typed. A transcript is full of things that were said and not meant —
half-sentences, options the room rejected, somebody thinking aloud — and a tool that filed those
as decisions would have made the pool *less* trustworthy, not more full.

**`none` is a normal answer** and most stretches of most meetings deserve it. That is the opposite
default from the one the message splitter uses, and the asymmetry is deliberate: an unparsed
message is something somebody definitely typed, so losing it is the only failure there. An
unparsed stretch of transcript is a model's reading of a room, and inventing from it is the only
failure here.

**It reads in passes.** A transcript does not fit in one useful prompt, and one answer over forty
minutes of talk comes back as four bland lines. Each pass is bounded, and its ideas are captured
before the next one runs — so a read that is interrupted keeps what it already found.

Everything it writes goes through the same placement as a typed thought
([`05-ideas.md`](05-ideas.md)), so a meeting that restates last week's decision does not fill the
pool with it a second time.
