# ADR 0002 — read always, write only on a human click

**Status:** accepted · 2026-09-02

## Context

The tool needs to know what several running agents are doing. Two ways exist.

**Ask them.** Claude Code sessions expose a peer-messaging socket, and a session can be sent a
message and answer it. This is accurate and current: it reports intent, not just evidence.

**Read what they leave on disk.** The registry gives status, project and title; transcripts give
the request stream and the last action ([03-session-observation.md](../03-session-observation.md)).
This is evidence only, and it can lag.

## Decision

Read continuously. Never message a session from any automatic path. The single write path is one
route reached by a human clicking a button that names the session and shows the message first.

`agent_desk/observe/` and `agent_desk/answer/` do not import the peer-messaging client, and a test
asserts the import graph.

## Why

A message to a session **lands in that session's context window**. It is not free, it is not
side-effect-free, and it does not merely cost tokens: it displaces the work in progress and takes
the agent's attention off the thing it was holding in its head.

That is problem 3 of [01-vision.md](../01-vision.md) — the reason the developer stopped talking to
their agents about ideas in the first place. A status board that polls agents for status would have
solved problem 1 by making problems 2 and 3 worse, and it would do so invisibly: the board would
look excellent while the runs behind it got slower and more confused.

Reading has none of these properties. It is a file open. The observed session cannot tell it
happened.

## Consequences

**Accepted: the board is behind and cannot report intent.** It shows what an agent *did*, not what
it *means to do*. Where that matters, the board names the session to go look at rather than
guessing ([03-session-observation.md](../03-session-observation.md), "What cannot be known").

**Accepted: no automatic idle-queue.** The obvious next feature — hold a message and deliver it when
the session goes idle — is a rule that decides a good moment, and this tool cannot see inside the
work well enough to have that judgement ([08-non-goals.md](../08-non-goals.md) §2).

**Rejected outright: `tmux send-keys`.** It is available and it is an interruption in an automation
costume ([08-non-goals.md](../08-non-goals.md) §3).

## How it is enforced

The import-graph test is the mechanism, and it is deliberately structural rather than a review
habit: a rule that depends on remembering it holds until the first hurried afternoon.
