# Console

One window, full screen, three columns: what is running, what you are asking, and what is in the
way.

```
┌─ agent-desk ─────────┬─ chat 1 │ the migration │ + ──────────┬─ blockers ───────┐
│ ▾ DuckyFlow      3 ⚑ │                                       │ ○ waiting on a   │
│   ▾ llm-developer-2  │  ┌ session · Docker client ────────┐   │   person   soon  │
│     ● Docker client  │  │ where  llm-developer-2 · duck-1 │   │ ● waiting on a   │
│       working  2m    │  │ asked  what about timeouts      │   │   run      soon  │
│       user [Bash]    │  │ did    22:01 assistant reading… │   │ ● failed and     │
│       what it is do… │  └─────────────────────────────────┘   │   unattended     │
│   ▾ llm-developer-1  │                                       │                  │
│     ○ Lane ports   ⚑ │  what did it end up doing about tim…  │  placeholders,    │
│       idle 14m       │  ┌ it kept the ninety-second timeout │  and drawn as     │
│       may want you   │  │ and logged the retry. …           │  placeholders     │
│ ▸ agent-desk      1  │                                       │                  │
│ [new project…]    +  │  › ask, record an idea, or say what   │                  │
└──────────────────────┴───────────────────────────────────────┴──────────────────┘
```

## What the parts are called

The names are used in the code, in these documents and out loud, so that "the thing on the left"
stops being how anybody refers to it. The owner's Russian is beside each, because this is a
bilingual project and half the requests arrive in it.

| Name | Где | What it is |
|---|---|---|
| **overview** | овервью | the left column: subscriptions, projects, checkouts, consoles, agents |
| **workbench** | верстак / рабочий стол | the middle: a surface things are carried onto and worked with |
| **input** | ввод | the bottom of the workbench, where a message is typed |
| **blockers** | блокеры | the upper right: what is in the way |
| **idea pool** | пул идей / бэклог | the lower right: what has been written down and not yet built |

Any of them can be resized by dragging the handle beside it, and any except the input can be put
away — a screen at four in the afternoon is not the one somebody wanted at ten. What is showing
and how wide it is lives in the browser, not the store: it is a preference about a window, not
data about the work.

## The three columns

**Left: what is running**, as cards inside cards — a project holds checkouts, a checkout holds
consoles, a console holds what it farmed out. A card carries what somebody who does not read code
needs in order to decide whether to look: what it is called, whether it is working, when it last
moved, one line of what it last did, and whether it may want them. Everything else is *detail*,
and detail belongs where somebody asked for it.

**Middle: what you are asking.** Empty until you ask something. Chat tabs across the top, one by
default and `+` for another; under them the output, where every message hangs with its answer
underneath it; under that a small input field. Clicking a card, or dragging one into the output,
opens what it contains *there* — and while it sits there, that is what the next message is about.
Dragging it back out undoes both. With nothing in the output the run is given the whole board and
works out from it what the question is about, which is what somebody who has not chosen wants
rather than an error asking them to choose.

**Right: what is in the way.** Mirrors the left column's cards. Every card in it is a placeholder
today and says so: nothing on disk states what is blocking a session, and a blocker this program
cannot observe is one it will not invent.

The middle is for somebody watching work they are not doing — often somebody who does not read
code — so an answer there is two or three sentences of ordinary words with the answer in the first
one, and never a wall of technical prose. That instruction is in the prompt, not in a hope
([04-threads-and-blocks.md](04-threads-and-blocks.md)).

## The board

Sessions are not a flat list, because nobody has a flat list in their head. Four levels, and every
one of them is derived rather than declared — a level somebody had to maintain by hand would be
wrong the first time they forgot ([03-session-observation.md](03-session-observation.md)):

| Level | What it is | How it is known |
|---|---|---|
| an agent | a subagent a session started | an `Agent` tool call in the transcript, and the result that ended it |
| a session | one console | one registry entry |
| an instance | one checkout on this machine | the session's working directory |
| a project | one or more repositories | a worktree's pointer and the `origin` in a git config — or a human saying so |

The default grouping needs no button: every checkout of one origin is one project. The button is
for the case the default cannot know — an API and an app in two repositories that are obviously one
product — and it produces an empty card to drag other cards into. Ungrouping returns every
repository in it to being its own project; nothing is lost by it.

**There is no progress bar, and there will not be one.** Nothing on disk says how far along a
session or a subagent is. A bar that moved without knowing would be the guessed status this whole
board refuses to render ([03-session-observation.md](03-session-observation.md), "What cannot be
known"). What a card shows instead is what is true: the status the session wrote, what it last did
and when, and which subagents are still out.

Each card: the status as a word anybody can read — `busy` is rendered "working", `shell` is
"running a command", and the registry's own word is on the tooltip, because this renders a fact
rather than replacing one — the session's own generated title, how long since anything changed,
and one line of what it last did. The branch, the question it was asked, the full last entry and
what it farmed out are on the card that opens in the middle.

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

Clicking a card opens it in the middle, which is the whole drill-down: v1 has no transcript
viewer, no diff view and no tool-call browser. The board answers "should I go look", and the place
to look is the terminal that is already open.

The card is a native disclosure, which is what makes it reachable from the keyboard, announced by
a screen reader, and openable with no JavaScript at all — the tail then loads through a plain link
inside it instead of a fetch. `/` puts the cursor in the input field from anywhere and Escape closes the
write-path panel, because this window hovers over a terminal and reaching for the mouse is the
thing it exists to save.

## The input and the output

One field, always focused, never blocked, and a plain HTML form underneath. Submitting frees it
immediately ([04-threads-and-blocks.md](04-threads-and-blocks.md)). What was typed appears in the
output above it and its answer arrives underneath it, on its own time; the next thing can be typed
while it does.

Three things arrive through that one field and each gets what it asked for: a question is
answered, a thought is recorded and says so, and an instruction to a session is written out as a
message and waits for the click that sends it. Which of the three it was is decided by a run
rather than by the person typing ([04-threads-and-blocks.md](04-threads-and-blocks.md)).

A tab is a subject. Typing in one is how a human says which subject this is, so nothing has to
guess it — which is the "default and a click" [09-roadmap.md](09-roadmap.md) names as what should
replace the thread classifier if it ever costs more attention than it saves.

Prefixes for when you already know what you want: `/new` forces a new thread, `/idea` forces
capture and skips classification entirely.

htmx makes every swap happen in place; when it is not vendored the console's own script does the
same posts itself, and with no JavaScript at all every control is still a form with a method and
an action that answers a whole page.

## The overlay

The point is that it hovers. A tab among thirty is a tab you do not look at.

v1 ships a `make overlay` target that opens the same URL in a dedicated Chromium app window
(`--app=`) with a stable window class, so a window rule in the desktop environment can pin it
always-on-top. That is a shell command and a paragraph of setup notes, against several days for a
desktop wrapper that would render the same HTML ([08-non-goals.md](08-non-goals.md)).

It is a local page over plain HTTP on `127.0.0.1`, and it opens in a normal browser as well.

## What the console must never grow

No button that **steers** an interactive session — no follow-up into a running context, no
keystrokes, no `tmux send-keys`. No button that edits a file in an observed repository. No
approval, no merge, no "mark as done".

Two things on that list moved, each deliberately and with an argument.

[adr/0006](adr/0006-the-desk-may-start-work.md) allows a written instruction to **start** a new
background agent, in a git worktree of its own, when a human clicks. Starting is not interrupting:
a session that does not exist yet has no context to displace. It can be stopped from here and it
cannot be steered from here.

[adr/0007](adr/0007-a-loop-that-decides-when-not-what.md) allows a loop to decide **when** to start
something a human already queued, and [adr/0008](adr/0008-an-agent-that-finds-its-own-work.md) lets
a project that was switched on for it find its own work when the queue is empty — one defect at a
time, marked as found by an agent wherever it appears, never merged. It never invents a task, never reads a
tracker for work, and never queues anything itself. It is off in every project until somebody arms
that one, starts one agent at a time, spends a small hourly budget, runs only while this console
is open, and switches itself off after two starts in a row fail. What it will not do is the half
that matters: an agent that goes looking for its own work is a different feature and a different
argument.

This tool watches work it does not own, and the moment it can change that work it needs to be
trusted the way the thing doing the work is trusted — an audit trail, a permission model, an
identity. That is a different program ([adr/0001](adr/0001-a-separate-repository.md)).

The single exception is the one path in [adr/0002](adr/0002-read-first-never-interrupt.md):
a message to a named session, shown in full before it goes, sent by a human clicking send. It is a
message, not a command, and the session's own permission rules apply to it exactly as they do to
anything its human types.

Its surface is a `message this session…` link on the card and a panel under the output — outside it, because
the board replaces itself whenever a session changes and a panel inside it would vanish under a
half-typed message. The panel has three steps and no shortcut between them: compose, the message
rendered in full beside the name and status of the session that would receive it, and what
happened. **Today the last step always reports a refusal**, because the installed CLI publishes no
client for its cross-session socket; the panel then offers the text back to be pasted by hand
([09-roadmap.md](09-roadmap.md), Phase 3).
