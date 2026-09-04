# Console

One window, two regions: a board of sessions, and a column of blocks under an input field.

```
┌─ agent-desk ───────────────────────────────────────────────────┐
│  llm-developer-2 · boba/duck-129-docker-api                    │
│  ● busy   "Docker client for the supervisor"      2m ago       │
│                                                                │
│  llm-developer-1 · main                                        │
│  ○ idle   "Lane ports security review"           14m ago  ⚑    │
│                                                                │
│  Project Zomboid My Mods · —                                   │
│  ○ idle   "Sandbox options parsing"               3h ago       │
├────────────────────────────────────────────────────────────────┤
│  › what did the docker client end up doing about timeouts_     │
├────────────────────────────────────────────────────────────────┤
│  ▸ running   what did the docker client end up …               │
│  ▸ answered  is duck-129 pushed?              → thread: duck   │
│  ▸ idea      cache the probe results          [Keep] [Discard] │
└────────────────────────────────────────────────────────────────┘
```

## The board

One row per live session, from the registry ([03-session-observation.md](03-session-observation.md)).
Each row: project, branch, status, the session's own generated title, and how long since anything
changed.

**Sorted by what needs a human, not by recency.** Sessions inferred to be waiting first, then
`busy`, then `idle`. Sorting by `updatedAt` puts a session that flickered twice above a long
healthy run, which is exactly backwards for a board whose job is triage.

The ⚑ marks the inference "may be waiting for you", and hovering it shows the observation behind
it — `idle 14m · last entry: assistant` — or, where the `Notification` hook is installed, the
event itself. The two are visibly different, because one is a guess and one is a fact.

**A board that has stopped updating says so.** The page shows when it last heard from the server
and marks itself lost the moment the stream drops **or simply goes quiet for longer than the poll
interval allows**, dimming what it is still displaying. A console
that quietly froze looks exactly like a console on which nothing is happening, and that is the
same failure as a guessed status: something inferred from silence, rendered as a fact
([03-session-observation.md](03-session-observation.md)).

A row expands to the tail of that session's transcript. That is the whole drill-down: v1 has no
transcript viewer, no diff view and no tool-call browser. The board answers "should I go look",
and the place to look is the terminal that is already open.

## The input and the blocks

One field, always focused, never blocked, and a plain HTML form underneath — htmx makes the
submission update the column in place, and without it the page reloads and the field is free just
the same. Submitting frees it immediately
([04-threads-and-blocks.md](04-threads-and-blocks.md)). Blocks appear below, newest first, each
showing its state and its thread. An idea block shows its card ([05-ideas.md](05-ideas.md)).

Prefixes for when you already know what you want: `/new` forces a new thread, `/idea` forces
capture and skips classification entirely.

## The overlay

The point is that it hovers. A tab among thirty is a tab you do not look at.

v1 ships a `make overlay` target that opens the same URL in a dedicated Chromium app window
(`--app=`) with a stable window class, so a window rule in the desktop environment can pin it
always-on-top. That is a shell command and a paragraph of setup notes, against several days for a
desktop wrapper that would render the same HTML ([08-non-goals.md](08-non-goals.md)).

It is a local page over plain HTTP on `127.0.0.1`, and it opens in a normal browser as well.

## What the console must never grow

No button that starts, stops, or steers an interactive session. No button that edits a file in an
observed repository. No approval, no merge, no "mark as done".

This tool watches work it does not own, and the moment it can change that work it needs to be
trusted the way the thing doing the work is trusted — an audit trail, a permission model, an
identity. That is a different program ([adr/0001](adr/0001-a-separate-repository.md)).

The single exception is the one path in [adr/0002](adr/0002-read-first-never-interrupt.md):
a message to a named session, shown in full before it goes, sent by a human clicking send. It is a
message, not a command, and the session's own permission rules apply to it exactly as they do to
anything its human types.

Its surface is a `message…` button on the row and a panel below the board — outside it, because
the board replaces itself whenever a session changes and a panel inside it would vanish under a
half-typed message. The panel has three steps and no shortcut between them: compose, the message
rendered in full beside the name and status of the session that would receive it, and what
happened. **Today the last step always reports a refusal**, because the installed CLI publishes no
client for its cross-session socket; the panel then offers the text back to be pasted by hand
([09-roadmap.md](09-roadmap.md), Phase 3).
