# ADR 0005 — one door out to a tracker, and a human standing in it

**Status:** accepted · 2026-09-04

## Context

[05-ideas.md](../05-ideas.md) says the drafts are the deliverable and names the corollary
explicitly: *"an action that writes outside `~/.local/share/agent-desk/` is not a feature of the
ideas module. If one is ever wanted, it is an ADR, not a commit."*

One is wanted. The owner of this machine asked for a button on an idea that files it in Jira.

The reasoning behind the original rule has not changed, and it is worth restating before it is
narrowed, because the narrowing has to be shaped by it. The failure it prevents is a queue that
fills itself: the information lost between an idea and a written ticket is *a human deciding it is
worth doing*, and a tool that closes that gap automatically has not saved the step, it has removed
the review that made the artefact worth reading. A backlog nobody chose to fill is a backlog
nobody trusts, and the ideas inbox becomes a drain rather than a notebook
([09-roadmap.md](../09-roadmap.md), "What is measured").

So the question this ADR answers is not "may this program write to Jira" in general. It is: **what
shape of write keeps the deciding human in the middle of it?**

## Decision

One route files one idea into one tracker, and every part of that sentence is load-bearing.

- **A human clicks, having read what will be sent.** Two steps, no shortcut between them: the
  ticket rendered in full beside the destination it would land in, and then a button. This is the
  same shape as [0002](0002-read-first-never-interrupt.md)'s message panel, for the same reason —
  the cost of the next step is somebody else's queue.
- **Only an idea that was kept and drafted.** `new` cannot be filed. The ticket body is the
  `ticket` draft, which exists because somebody asked for it and could read it. Three deliberate
  human acts stand between a typed thought and an issue: keep it, draft it, file it.
- **No credential is stored.** The token comes from an environment variable named per project
  (`project_link.token_env`), never from the database
  ([../../design/02-data-model.md](../../design/02-data-model.md)). This program can say what it would
  use without ever holding it.
- **`agent_desk/tracker/` is importable only from `agent_desk/web/`**, asserted by the same
  import-graph test that guards the peer-messaging path. No background task, no answer run and no
  observer can reach it.
- **One direction, once.** It creates an issue. It does not read Jira, poll it, mirror a status
  back, update an issue, or transition one. An idea records the key it was filed as and stops; a
  second click on a filed idea does nothing but show the key.
- **The failure is reported, never retried.** A refusal, a timeout or a 400 is rendered against the
  idea with what came back. Nothing here retries: a retry loop against somebody's tracker is the
  automatic queue this ADR exists to avoid, arriving through the back door.

## Why this is not the failure the rule was written about

The rule protects a decision, not a directory. What made "integrate into the documentation"
dangerous was that *nobody read the thing being written*: the tool closed the loop and the artefact
appeared in a place where artefacts are trusted.

Here the loop stays open in the only place that matters. The ticket that lands in Jira is a
document a human generated on purpose, read on a screen, and then pressed a button to send. The
program's contribution is the typing and the context, which is what it was for.

It is also worth being plain about the alternative. Without this, the path is: read the draft,
select it, copy it, open Jira, paste it, retype the title. Every one of those steps is a place to
lose the thing, and none of them is the review — the review already happened when the draft was
read. Refusing the button does not preserve a decision; it just makes the same decision more
tedious to act on.

## Consequences

**Accepted: this program now makes an outbound network request.** It had none. One host, named by
a link a human typed, reached only on a click, carrying only the idea's own draft. That is a new
line in [07-security.md](../07-security.md) and it is drawn narrowly on purpose: no other
destination, no other payload, no other trigger.

**Accepted: the draft is what is filed, not something better.** The tool does not improve the
ticket on the way out, because then what was reviewed is not what was sent.

**Rejected: reading Jira back.** Status, comments, transitions, a "filed" column that stays in
step — that is a tracker client, and this is a notebook that can post once
([08-non-goals.md](../08-non-goals.md) §4). An idea that was filed says so and links out; what
happened to it afterwards is Jira's to answer.

**Rejected: filing automatically, on any signal whatsoever.** Not on capture, not on keeping, not
on a threshold of importance, not on a schedule. There is no path to this route that does not pass
through a person.

**Rejected: storing the token.** Named above; the reason is in the migration and in
[../../design/02-data-model.md](../../design/02-data-model.md). A tool that holds a tracker credential
is a tool with a rotation policy and an audit trail, and that is a different program
([0001](0001-a-separate-repository.md)).

## How it is enforced

The import-graph test, extended: `agent_desk/tracker/` joins `agent_desk/peer.py` as a module only
`web/` may import. Both are doors out of this program, both are opened by a click, and the test is
what keeps that true after the first hurried afternoon.


## Amended by 0010

The refusal to read a tracker *back* was written here as a corollary rather than argued, because
nobody had asked for it. [0010](0010-reading-a-tracker-back.md) argues it, and narrows it: this
document's reasoning is about *writing*, and none of it reaches reading. The door out is unchanged
— reading queues *tasks*, never ideas, and writes nothing back at all.
