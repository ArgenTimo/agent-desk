---
name: ticket-intake
description: Readiness skill — read the ticket and everything it links to, decide whether the work can start, and produce blocking questions when it cannot. Runs in `intake` mode at the start of a run and again after a human answers. Produces structured JSON only; writes nothing to the workspace, creates no branch, edits no file. Triggers when the orchestrator starts a run in intake mode. MUST NOT activate in any writing mode, MUST NOT ask a question the repository already answers, and MUST NOT start implementing "while it is here".
metadata:
  scope: project
  author: ai-worker
user-invocable: false
disable-model-invocation: false
---

## The two layers

The deterministic preflight has already run before you are invoked — the ticket exists, the
label was present, no other run is active, the round limit is not exhausted. Your layer answers
a different question: **do I understand what to build?**

## Process

1. Read the ticket: summary, description, acceptance criteria, comments (all of them — the
   answer to an earlier question is often the last comment on a long thread), linked issues.
2. Read the linked context: design frames, requirement pages. They are read-only.
3. Locate the affected area in the repository. Read the code and its existing tests.
4. Restate the task in one paragraph.
5. Separate what you can assume from what you must ask.

## The assumption / question test

A question is **blocking** only when the answer changes what you build and no reasonable default
exists. Everything else is an assumption: write it down with its evidence and proceed.

| Example | Verdict |
|---|---|
| "Should archived rows be included?" | blocking — changes the query and the test |
| "Which test framework?" | not a question. The repository answers it. Asking is your failure. |
| "Should I follow the existing naming?" | not a question. Read it and follow it. |
| "Sync or background job?" | blocking if the ticket implies scale; otherwise an assumption with a stated basis |

Rules:

- **At most five questions.** More than five means the ticket is unscoped rather than
  under-specified. Set `ready: false`, `needs_decomposition: true`, ask nothing, and propose a
  split.
- **Every question carries its consequence** — what changes depending on the answer. A question
  without one spends a human's attention at no benefit.
- **Offer options** where the answer is a choice. A closed question is answered in five seconds;
  an open one waits until evening.
- **Assumptions are visible.** A human can object to a written assumption; they cannot object to
  one you kept in your head.

## Output

```json
{
  "understanding": "One paragraph.",
  "affected_area": ["path/to/module", "path/to/tests"],
  "assumptions": [{"text": "...", "basis": "file.py:88", "risk": "low|medium|high"}],
  "questions": [{"text": "...", "why_blocking": "...", "options": ["a","b"]}],
  "needs_decomposition": false,
  "proposed_subtasks": [],
  "ready": true
}
```

`ready` is true only when `questions` is empty. When unsure whether something is blocking, it is
an assumption.

## Budget

The project's question budget (default 10 per ticket, across all rounds) is enforced by the
orchestrator, not by you — but you are told how many remain. When few remain, spend them on the
answers that change the most, and convert the rest to assumptions. Ten unanswered unknowns is
not a communication problem to solve with an eleventh question; it is a ticket that was never
ready, and the honest response is to say so.
