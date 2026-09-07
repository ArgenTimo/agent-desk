# ADR 0011 — a blocker a model grouped, and how it says so

**Status:** accepted · 2026-09-07

## Context

[0010](0010-reading-a-tracker-back.md) let this console read a board and record what a *ticket*
says about being stuck: one row per ticket, the ticket's own sentence quoted, its key beside it.
That is the right shape for a ticket, and it is the wrong shape for the place people actually
write down what they are waiting on, which is the comments.

Asked for, in these words:

> «пройди по таблице Jira, собери из комментариев к задачам в колонке In Review все упомянутые
> блокеры. Сгруппируй их семантически в укрупнённые задачи для человека и к каждой напиши короткий
> туториал — что конкретно нужно сделать, чтобы разблокировать. Результат положи в проект, в поле
> блокеров.»

A review column of eight tickets carries eleven such sentences, and between them they are three
problems: the staging credential nobody has rotated, the design decision nobody has taken, the
dependency nobody has released. Rendering eleven cards makes a person do that grouping in their
head, from scratch, every time they open the board — which is the work this console exists to
save.

## The problem this creates

Every other card in the blockers column is a fact this console observed: a task it started that
failed, a switch that turned itself off, a sentence a ticket wrote. CLAUDE.md's fifth rule is
about exactly that difference, and a grouped blocker breaks it in two places at once. "These three
comments are the same problem" is a judgement. "Here is what to do about it" is a judgement about
a codebase and a team this console has never seen.

Neither is worthless — the grouping is the whole request, and a person who has to fix something
would rather start from a wrong list of steps than from a blank card. But a synthesis that renders
like an observation is worse than no card at all, because the column's value is that you can trust
it without opening a terminal.

## Decision

**A blocker may be a model's grouping of comments, and the card carries its evidence.**

- **The quotations are the record, the grouping is the reading.** `jira.read_review` produces
  `Mention`s: one sentence somebody wrote, and the key of the ticket it was written on. A model
  groups them and writes the steps; the sentences stored under a group are rebuilt from the
  mentions rather than taken from the reply, so what a card quotes is always what somebody wrote.
- **A key the model was not shown is dropped, and a group left with no key is dropped whole.** The
  one thing this must never do is attach a sentence to a ticket that did not say it.
- **The card says which half is which.** The heading and the steps are labelled as a model's
  reading, above the quotations they were read from. That labelling is the reason this is allowed
  at all.
- **It reads; it still does not tidy.** No transition, no comment, no assignment — 0010's refusal
  is unchanged, and "put the result in the project" means this console's own blockers column, not
  a field on somebody's board.
- **A pass that could not read replaces nothing.** An unreachable board and an unavailable model
  both leave the rows exactly as the last good pass left them. Only a board that was read and
  genuinely says nothing clears anything, because a column nobody could read must never look like
  a column with nothing in it — the same distinction 0010 took care over.

## Which column, and why not by name

The query asks for `statusCategory = "In Progress"` and matches the status *name* in Python
against a short list ("In Review", "Review", "на ревью", …). Categories are fixed in every Jira
and a review column is always in the middle one; a status name is a thing a team renames, and a
JQL naming a status a board does not have fails the whole request with a 400 rather than returning
nothing. A name nobody recognised costs one comparison; a query nobody can run costs the feature.

## Where it runs

Beside the pass that reads the idea pool, on a twenty-minute tick, for the same three reasons:
slow, one model call per project that has something to group, and allowed to fail. Not in the
autostart loop, which runs every thirty seconds and must stay cheap.

## What was rejected

**Storing the groups in `tracker_blocker`.** Its `said` column is documented as a ticket's own
sentence, quoted, and a synthesis in it would be indistinguishable from one a week later. A
separate table is four columns and keeps the two kinds of claim apart on disk, where it matters.

**Filing the groups back to Jira as issues.** The door out is one issue, filed once, because a
human pressed a button having read what would be sent ([0005](0005-one-door-out-to-a-tracker.md)).
A background loop that files eight issues an evening is that door held open by a brick.

**Turning a group into queued work.** What a person has to do here is rotate a credential, take a
decision, or wait for somebody else's release. An agent started on it would spend a worktree
discovering what the comments already say — the same reason 0010 keeps a blocked ticket out of the
queue.
