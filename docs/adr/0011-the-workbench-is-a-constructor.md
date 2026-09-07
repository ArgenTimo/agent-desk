# 0011 · The workbench is a constructor, not a canvas

**Status:** accepted · **Date:** 2026-09-07

## What was decided

The middle of the console stopped being a surface you *put things on* and became one you *build
things on*. A card now says what it is in a process; a line says what happens along it; a step
says what it does, what it may do, and what it is told; and the whole drawing can be run.

Five decisions, and this record exists because each of them closed a door that looked open.

## Why at all

The console was a good reader. You could see every session on the machine, drop the relevant ones
in front of you, and ask about them. The first user's feedback was that this was the smaller half
of what the surface was already worth:

> Верстак — это не просто работа с контекстом. Это конструктор. Всё вокруг нас — абстракция,
> которую можно описать и создать конструктор. Описываем процесс как в лего… где под капотом
> контекст + агент + тулзы + пермишены + память + конкретное выполнение по порядку, то есть движок.

He is right, and the reason is narrow enough to state: a surface where every card is a *thing that
already exists* can only ever describe the present. To describe work that has not happened yet you
need boxes that stand for nothing, and lines that mean something.

## 1 · Five roles, and a role is not a kind

`agent_desk/roles.py` · migration 033

Object, Action, Decision, Event, Result. Five because that is what every process notation
converges on: a thing, a step, a fork, a trigger, an outcome. Six is a taxonomy somebody has to
learn; four leaves you unable to say when something starts.

The decision that mattered was **not reusing `kind`.** A card's kind — session, idea, blocker,
folder — says where it is read from, and it cannot change: an idea does not become a session. Its
role says what it is doing in the process being described, and it changes as the description does.
One field cannot carry both, and the version that tried would have made "this idea is the Result of
that step" a thing you could not say.

**Absent is a real answer.** Every kind has a role it naturally is — a session is an Action, a
blocker an Event — and a stored row is somebody having said otherwise. Requiring five cards to be
typed before one line can be drawn is how a constructor goes unused.

**Drawn as shape, never colour.** On this page colour means status and nothing else
([`06-console.md`](../06-console.md)), a rule older and worth more than this feature — and shape is
what was asked for anyway: a diamond reads as a decision before the text inside it is read.

## 2 · Five kinds of line

`agent_desk/ties.py` · migration 034

then · if · when · makes · with. A line that says only "these two are related" is a picture: read a
bench of them and you learn that somebody thought six things belong together, which you already
knew, because they are on the same bench. A line that says *then*, *if*, *when* is a sentence.

`makes` is separate from `then` because "what came out of it" and "what happens next" are
different questions. `with` is kept because most lines somebody draws are that, and forcing a
process meaning onto them would make the other four mean less; it is also the only one without a
direction.

**Suggested, never enforced.** The kind comes from the roles at both ends, so drawing out of a
diamond gives a branch before anybody chooses anything. Nothing refuses a line that reads
strangely: somebody sketching a process is thinking, and a constructor that rejects your line
because the boxes are not yet the right shape is a constructor you fight.

**The ends are card names, not foreign keys.** A process runs from an idea through a session to a
blocker, and only one of those three is a row in this database. `idea_link` (024) could not have
carried it without a column per kind of thing that exists.

## 3 · A small fixed set of fields per role

`agent_desk/roles.py` · migration 035

> Поле, которое можно назвать как угодно, — это снова свободный текст, а свободный текст движок
> исполнить не может.

That sentence is the whole design. A card with a free-form list of fields is a card with a note on
it: readable by a person and by nothing else. Each role gets a handful, validated before anything
is written, so "what does this step do" has one answer in one place.

Decision asks only for its condition. Its branches are the `if` lines going out of it, because
that is where somebody draws them — a "branches" field on the card would be the same information
twice, wrong from the moment the two disagree.

**Needed is shown, never enforced.** Half-drawn is the normal state of a diagram somebody is
thinking in. What is missing is marked in amber, not red: red means stopped, and a step nobody has
finished describing has not stopped, it is being written.

## 4 · Permissions that say whether they are held or only asked for

`agent_desk/allowed.py` · migration 036

> Это то, что отличает конструктор, которому можно доверить запуск, от схемы, которую страшно
> нажать.

The value of a permissions screen rests on a distinction they usually hide. `read`, `work`, `land`
and `push` are **enforced** — each names a branch in this program's own code: whether an agent is
started at all, in which directory, whether the landing is called, whether it is asked to push.
`net` is **asked** — it goes into the briefing in words and nothing here stops an agent that
ignores it.

Each switch says which it is. A row of switches that look alike but do not work alike is worse
than no switches: it is a guessed status wearing a checkbox, which is
[`CLAUDE.md`](../../CLAUDE.md) rule five broken in a new place.

A permission for something nothing in this program reads would be a switch that does nothing.
There is a test that every `enforced` one names code that exists.

## 5 · The engine queues; it does not start

`agent_desk/web/engine.py` · migration 037

This is the decision the whole engine is built around and the one that makes it safe to add here
rather than beside here.

The console already knows how to start work carefully: a project has to be armed, one agent at a
time, an hour's budget, two failures in a row switch it off ([`adr/0007`](0007-a-loop-that-decides-when-not-what.md)).
An engine calling `dispatch.start` itself would be outside every one of those, and the first
anybody would know is a drawing with nine steps starting nine agents at three in the morning.

So a step becomes a queued task, the way "build it" and a deferred idea already do, and the loop
that exists starts it under the rules that exist. The engine's whole job is sequencing. There is a
test asserting it never calls `dispatch.start` — against the syntax tree, because the module is
*about* dispatching and the word is all over its prose.

Three consequences follow:

- **A failed step stops the run.** The steps after it were described on the assumption that it
  worked; running them anyway is how a process produces confident wrong output.
- **An Event holds rather than fails.** A run waiting on Friday's release is a run that is fine,
  and a console showing it in red would have somebody hunting a fault. Saying it happened is a
  human act, because whether the release went out is not something this console can read.
- **The cards are frozen into the run**, the lines and fields are not. What is on a workbench is a
  fact about a browser and it changes while a run is going; correcting the wording of a step that
  has not started yet should be used.

## What this does not change

Nothing here loosens the five rules. The engine writes into no observed repository, opens no
credential, reports no inferred status as known, and reaches a running session only through the
door [`adr/0002`](0002-read-first-never-interrupt.md) describes. `process.py`, `roles.py`,
`ties.py`, `allowed.py` and `telling.py` are pure — no store, no clock, no subprocess — because an
engine whose ordering can only be observed by running agents is an engine nobody can test.

## What was rejected

**A visual programming language.** Loops, variables, types, a scheduler. Every one of those was
available and every one would have made this a worse tool: the thing being described is work, and
work is a handful of steps with a fork in it. The moment this needs `while`, the answer is that
somebody should write a script.

**Free-text roles and free-text line labels.** They read better and execute worse. Five names with
a meaning each is a language; a label with an arrow on it is a note.

**Starting agents directly** — see §5.

**A second surface for it.** A constructor mode beside the console would have been two workbenches
in one window, and the cards already on the bench would have been outside the typology looking in.
Instead every existing card has a natural role and is part of a drawing the moment somebody draws
a line to it.
