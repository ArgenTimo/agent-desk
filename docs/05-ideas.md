# Ideas

Problem 3 of [01-vision.md](01-vision.md): an idea arrives while agents are running, and every
place to put it is wrong. Typing it into a running session spends that session's context and
derails its run. Typing it into the repository's documentation makes a decision nobody agreed to.
Keeping it in your head costs the idea.

## The capture

An input classified as an idea produces, in seconds, a card:

```
┌────────────────────────────────────────────────────────────┐
│ Idea recorded                                              │
│                                                            │
│ Cache the tracker probe results per project so onboarding  │
│ does not re-run four API calls on every retry.             │
│                                                            │
│ [ Keep ]  [ Edit ]  [ Discard ]        thread: onboarding  │
└────────────────────────────────────────────────────────────┘
```

The one-line summary is generated; the original text is kept verbatim underneath and is what
survives. A summary is a convenience for scanning a list, and a summary that quietly replaced the
thought would be the tool losing the thing it was built to keep.

**Capture never asks a second question.** Keep or discard, one click. Anything more and the tool is
competing with the run it was supposed to stay out of.

## The inbox

Kept ideas go to a list, not into anyone's documentation. Each carries where it came from — the
project, the session that was running, the branch, the time — because "what was I doing when I
thought this" is most of an idea's meaning a week later.

An idea has exactly four states: `new`, `kept`, `promoted`, `dropped`. There is no priority field,
no assignee, no estimate. That is a backlog, and a backlog needs a process to stay honest; this is
a notebook that remembers its context ([08-non-goals.md](08-non-goals.md)).

## Promotion, and the one dangerous button

An idea can grow up. The actions are:

| Action | What it produces |
|---|---|
| **Draft a proposal** | a markdown file in agent-desk's own store: the idea, the context it was captured in, what it would change, and what it would cost |
| **Draft a ticket** | the same, shaped as a ticket body, on the clipboard |
| **Copy for a session** | the text, formatted to paste into a session yourself, at a moment you choose |

All three produce **text in this tool**. None of them writes into another repository, opens a pull
request, or files a ticket.

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
is not a feature of the ideas module. If one is ever wanted, it is an ADR, not a commit.

## Where the non-technical teammate fits

Problem 5 of [01-vision.md](01-vision.md) lands here rather than in the console: what a
non-developer needs is exactly this — a box to put an idea in, and a list of what happened to the
ideas already there. That view is Phase 3 and gated on redaction, because the context an idea
carries includes a branch name, a project and a moment in a transcript
([07-security.md](07-security.md)).
