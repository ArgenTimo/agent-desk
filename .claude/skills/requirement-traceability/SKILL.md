---
name: requirement-traceability
description: Every change traces to a stated requirement — a ticket's acceptance criteria, a spec artifact, or a document in the project's own docs — and a change that contradicts one updates it in the same commit. ACTIVATE before writing code, when a task seems to need behaviour nothing describes, and when code and a document disagree. Triggers on "implement X", "why is it like this", "почему так". MUST NOT be used to justify implementing something a document forbids by quietly editing the document.
metadata: {scope: project, author: ai-worker}
user-invocable: true
disable-model-invocation: false
---

## Find the requirement first

Before writing code, name what the change serves: an acceptance criterion on the ticket, a spec
artifact for the feature, a rule in `CLAUDE.md` or the project's documentation. If nothing does,
that is itself the finding — either the ticket is under-specified (ask, once, during intake) or
the work is unrequested.

The rule sources this project actually has are recorded in the profile under
`detected.rule_sources`. If that list is empty, the project has no written conventions, and every
choice you make will be resolved from the code's existing patterns instead. Say so in the report:
it is useful information about the project, and it explains why arbitration returns `undecidable`
often here.

## When code and a document disagree

| Case | Action |
|---|---|
| the document is right, the code drifted | fix the code |
| the document is stale | fix the document **in the same commit**, and say so in the message |
| you disagree with the documented trade-off | say so in the pull request; do not implement the other thing and adjust the prose |

The third row is what erodes a project's documentation. A document that stopped matching the code
is worse than none, because the next person will trust it.

## Commit messages

Name the requirement:

```
export: include archived rows behind a filter

PROJ-118 acceptance criterion 2. The default stays "exclude" so existing
saved views do not change meaning.
```

A reviewer should never have to ask which requirement a diff came from.

## In the report

The pull-request body carries `Requirement:` as a line, not as an implication. When a change had
no requirement — a drive-by fix, a rename you needed — say that too. An unexplained file in a
diff costs a reviewer more attention than the change itself was worth.
