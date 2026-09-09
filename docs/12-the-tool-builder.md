# The tool builder

> «Отдельная крупная фитча — конструктор инструментов. В нашем случае это уникальная карточка, в
> которую можно закладывать разнообразный ф-ционал… Пересмотри те сценарии, что я указывал, и
> посмотри, что необходимо для их реализации в этой новой сущности.»

A tool here is **a card that holds behaviour and is kept under a name**. Everything else on the
workbench stands for something that already exists — a session, a project, a file, a thought. A tool
is the one you make.

This document is the review the idea asked for: what the builder is made of, what each recorded
scenario needs from it, and what it is deliberately not.

## What a tool is made of

| Part | What it is | Where |
|---|---|---|
| a button | a card holding a request, sent when pressed | [059](../agent_desk/store/059-a-card-that-is-a-button.sql) |
| a check | a card holding a condition, saying one of two things about an answer | [062](../agent_desk/store/062-a-card-that-checks.sql) |
| a name | kept in the list beside the projects, outliving every chat | [065](../agent_desk/store/065-a-tool-you-keep.sql) |
| a description | a tool made from a sentence about one | [`tooling.py`](../agent_desk/tooling.py) |
| in and out | a card's label names what it holds; `{that name}` downstream is where it goes | [`slots.py`](../agent_desk/slots.py) |
| a connector | where else a project lives, and what this console can do with it | [`connectors.py`](../agent_desk/connectors.py) |
| an MCP server | a project lends it to the agents it starts | [074](../agent_desk/store/074-an-mcp-server-a-project-lends.sql) |
| coming back with cards | what an answer produces, instead of one paragraph | [075](../agent_desk/store/075-a-card-that-comes-back-with-cards.sql) |

Two kinds of behaviour and no third, and that is a decision rather than a stage of construction. A
tool a model was asked to invent a third kind for would produce a word this console cannot make a
card from, and "make me a tool that opens Jira" is answered by refusing rather than by making a
button labelled "open Jira" that does nothing of the sort.

## What each scenario needs, and whether it has it

Every scenario in the pool was read against the list above. This is the answer for each.

| Scenario | What it needs from the builder | State |
|---|---|---|
| alchemy — two cards make a third | a rule for what a combine asks, editable | [061](../agent_desk/store/061-the-rule-a-combine-follows.sql) |
| a check on an answer, and trying again | a check card, its verdict, a person's note on it | [062](../agent_desk/store/062-a-card-that-checks.sql), [064](../agent_desk/store/064-a-comment-on-a-check.sql) |
| a CV, a job, some nuances, a plan | cards a person writes, all of which travel | `tests/unit/test_the_employment_plan.py` |
| a card that goes and finds out | a button whose answer becomes cards | [075](../agent_desk/store/075-a-card-that-comes-back-with-cards.sql) |
| the harness — run, compare, check | a prompt step, a fan over models, spread, cost | [057](../agent_desk/store/057-what-a-run-was-given.sql), [058](../agent_desk/store/058-what-a-step-cost.sql) |
| measuring a prompt against a set | a check whose expected answer comes with the input | [072](../agent_desk/store/072-a-prompt-that-is-measured.sql) |
| an agent asks a person | a question card with options on it | [067](../agent_desk/store/067-a-question-for-a-person.sql) |
| two agents hand work over | a bench either can write to and read | `leave` and `bench`, [`mcp/tools.py`](../agent_desk/mcp/tools.py) |
| what an agent worked out | a fact with a reason and a source | [068](../agent_desk/store/068-what-was-worked-out.sql) |
| an agent with no browser | the page as text, and what its script said | [`seen.py`](../agent_desk/seen.py) |

Nothing in that table was missing a *kind of tool*. Two things were missing outright and were built
for this review: a project lending its MCP servers, and a button that comes back with cards.

## What it is deliberately not

**It does not claim to browse.** Whether the engine behind an answer can reach the internet is the
CLI's business and changes with its configuration. A card says what it does — it asks, and what
comes back becomes cards — and never that it went anywhere. This is the same rule that stops a
Google Drive connector from claiming to read a Drive.

**A tool never writes into a repository.** An MCP server is configured under `data_dir` and handed
to a starting agent with `--mcp-config`. A config file in somebody's checkout is the write
[CLAUDE.md](../CLAUDE.md)'s second rule refuses, and a person who looks at their tree afterwards
finds it as they left it.

**A tool holds no secret.** What is stored is the *name* of an environment variable. This is a
plain SQLite file that a second application already serves a redacted view out of
([07-security.md](07-security.md)), and a field to type a token into would put one in it.

**Keeping is a person's.** Making a card is cheap and undoable, so it happens on the asking;
keeping it is a decision about a list that outlives every chat, and it stays a separate press —
unless somebody asked for it to be kept, which is the parenthesis the original idea wrote.

## Where they live

In the list beside the projects, bottom left. A tool is put on any bench by name, and putting one on
a bench makes a copy: renaming or editing the kept tool leaves the one already on a bench working as
it was, because a control that changed under somebody's hand is a control they stop pressing.
