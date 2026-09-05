# Ideas

Problem 3 of [01-vision.md](01-vision.md): an idea arrives while agents are running, and every
place to put it is wrong. Typing it into a running session spends that session's context and
derails its run. Typing it into the repository's documentation makes a decision nobody agreed to.
Keeping it in your head costs the idea.

## The capture

An input classified as an idea produces, in seconds, a line per thought:

```
┌────────────────────────────────────────────────────────────┐
│ Cache the probe results — recorded as an idea              │
│                            [ Keep ] [ Discard ] [ Ticket ] │
│ cache the probe results per project so onboarding does     │
│ not re-run four API calls on every retry                   │
│                                                            │
│ Ports are still hardcoded — recorded as an idea            │
│                            [ Keep ] [ Discard ] [ Ticket ] │
└────────────────────────────────────────────────────────────┘
```

The one-line summary is generated; the original text is kept verbatim underneath and is what
survives. A summary is a convenience for scanning a list, and a summary that quietly replaced the
thought would be the tool losing the thing it was built to keep.

**Capture never asks a second question.** Keep or discard, one click. Anything more and the tool is
competing with the run it was supposed to stay out of.

**One message can hold several thoughts.** "Add A, B is broken, and we should probably C" is one
message and three ideas, and a person typing at speed does not stop to send three messages. So the
message is written down *first*, whole, as one idea and before any model is asked anything — that
is the guarantee, and the run is the part that can fail. A splitting run then either improves the
summary of the one thought it found, or replaces it with the several it did. It never invents one
that is not in the text, it never drops a part of what was written, and a card a human has already
touched is left exactly as they left it.

A source that proposes twelve at once — a meeting transcript — is still a review queue rather than
a card, and the shape of that queue is an open question recorded in
[`10-meeting-intake.md`](10-meeting-intake.md) rather than guessed at here.

## The inbox

Kept ideas go to a list, not into anyone's documentation. Each carries where it came from — the
project, the session that was running, the branch, the time — because "what was I doing when I
thought this" is most of an idea's meaning a week later.

The context is recorded as a **source** — kind, reference, and a free map — rather than as the
three session-shaped fields it would naturally have been. Today every idea has
`source_kind = "session"` or `"typed"`; the third kind is a meeting, and it costs one JSON column
to keep the door open ([`10-meeting-intake.md`](10-meeting-intake.md),
[`../design/02-data-model.md`](../design/02-data-model.md)).

An idea has five states: `new`, `kept`, `promoted`, `dropped`, `done`. There is no priority field,
no assignee, no estimate. That is a backlog, and a backlog needs a process to stay honest; this is
a notebook that remembers its context ([08-non-goals.md](08-non-goals.md)).

**An idea only leaves the column on evidence, never on a guess.** Three things move it, and they
are all somebody or something actually having done the work: a human pressing **built**, an agent
that was dispatched *for that idea* finishing, or the idea being filed as an issue — at which
point it is in somebody's tracker and no longer a thought waiting to be had. A run guessing that a
request "looks like it is about" an idea changes nothing at all; it draws a button. And while an
agent has it, the idea is coloured *in progress* wherever it is drawn, which is derived from that
agent still running rather than stored anywhere.

The fifth was four for three phases, and adding it was the right call for one reason: `dropped`
was the nearest word and it is the wrong one. *"We decided not to"* and *"it is in the product"*
are different answers to "what happened to my idea", and an inbox that cannot tell them apart
answers neither — it fills with thoughts that were built months ago and reads as a list of things
nobody did. A `done` idea leaves the column and keeps its place in the inbox. Nothing sets it from
a guess: a human presses **built**, or an agent dispatched *for that idea* finishes.

## Promotion, and the one dangerous button

An idea can grow up. The actions are:

| Action | What it produces |
|---|---|
| **Draft a proposal** | a markdown file in agent-desk's own store: the idea, the context it was captured in, what it would change, and what it would cost |
| **Draft a ticket** | the same, shaped as a ticket body, on the clipboard |
| **Copy for a session** | the text, formatted to paste into a session yourself, at a moment you choose |

All three produce **text in this tool**. None of them writes into another repository or opens a
pull request.

**One of them can now leave, and only by hand.** A ticket that has been drafted can be filed in
Jira: the ticket is rendered in full beside the project it would land in, and a button sends it.
Three human acts stand between a typed thought and an issue — keep it, draft it, file it — and
there is no path to that route that does not pass through a person. It creates an issue and stops:
nothing reads the tracker back, nothing retries, nothing files anything on a signal. That is
[adr/0005](adr/0005-one-door-out-to-a-tracker.md), which exists because the rule below said it
would have to.

That is the rule this page exists for, and it is worth being explicit about why, because "integrate
into the documentation" is the button everyone wants:

The ai-worker repository records this exact temptation as a deliberate omission — an idea arriving
in a chat message has no door into the system, because *a queue that fills itself is a queue nobody
trusts*. The information lost between an idea and a written ticket is the human deciding it is
worth doing. A tool that closes that gap automatically has not saved the step; it has removed the
review that made the artefact worth reading.

So the draft is the deliverable. A human opens it, reads it, and carries it into the target
repository through that repository's normal path — a branch, a review, a gate. The tool's job was
to make sure the thought was still there and still had its context. It did that.

**Corollary for anyone extending this:** an action that writes outside `~/.local/share/agent-desk/`
is not a feature of the ideas module. If one is ever wanted, it is an ADR, not a commit. One was
wanted, and it is [adr/0005](adr/0005-one-door-out-to-a-tracker.md) — which narrows rather than
lifts the rule: what leaves is a document a human generated on purpose, read on a screen, and
pressed a button to send.

## Where the non-technical teammate fits

Problem 5 of [01-vision.md](01-vision.md) lands here rather than in the console: what a
non-developer needs is exactly this — a box to put an idea in, and a list of what happened to the
ideas already there. That view is Phase 3 and gated on redaction, because the context an idea
carries includes a branch name, a project and a moment in a transcript
([07-security.md](07-security.md)).
