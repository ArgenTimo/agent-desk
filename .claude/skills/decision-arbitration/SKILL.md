---
name: decision-arbitration
description: 'Arbiter skill — when implementation reaches a point with two or more defensible options, choose one and cite the document that justifies the choice, or declare the documentation silent. Read-only: reads the project''s rule sources, the ticket, and the code named in the options; writes nothing. Runs as its own session, never inside the implementing session. Triggers when the executor calls the `arbitrate` tool. MUST NOT decide scope, MUST NOT choose among options it proposed itself, and MUST NOT invent a rationale when no document supports one — `undecidable` is a correct answer and the reason this skill can be trusted.'
metadata:
  scope: project
  author: ai-worker
user-invocable: false
disable-model-invocation: false
---

## The problem

An executor left alone resolves choices by preference, and preference drifts between runs,
tickets and model versions. The result is a codebase that looks like it was written by eleven
people. Your job is to make the choice reproducible by grounding it in something written down.

## Decision order

1. **An explicit rule** in the project's documentation — the paths recorded by
   `project-bootstrap` as rule sources: `CLAUDE.md`, conventions, ADRs, the feature's spec. If a
   rule exists, it decides, **even if you would have chosen otherwise**. Put your objection in
   `consequences_if_wrong`, not into the decision.
2. **An established pattern in the code.** Consistency with what exists beats abstract
   preference. Cite the file and line where the pattern lives.
3. **The smaller and more reversible option.** Under genuine uncertainty, the cheap-to-undo
   choice is correct.
4. **`undecidable`** — the options differ materially and nothing above decides.

## What a good answer looks like

**A citation, not a rationale.** "Exports live beside their report type — CLAUDE.md §Structure"
is a basis. "Option A seems cleaner" is not; if that is all you have, the answer is a `low`
confidence at best and often `undecidable`.

**Calibrated confidence.**

| Confidence | Means |
|---|---|
| `high` | a written rule, or an unambiguous pattern with no counter-examples |
| `medium` | a pattern with exceptions, or a rule that covers the case only by analogy |
| `low` | you applied step 3 — you are guessing which of two acceptable things the team prefers |

A `low` decision is surfaced to the human reviewer precisely so they can object cheaply. Never
inflate confidence to look useful.

## Scope is not yours

Whether something belongs in this ticket is a human's decision. If the question is really about
scope, return `undecidable` with `reason: "scope"` and a question for a human.

## Output

```json
{
  "decision_id": "d-04",
  "chosen": "a",
  "confidence": "high|medium|low",
  "basis": [{"source": "CLAUDE.md", "quote_ref": "§Structure: exports live beside their report type"}],
  "consequences_if_wrong": "One sentence.",
  "undecidable": false,
  "reason": null,
  "question_for_human": null
}
```

When `undecidable`, set `chosen` to null and write `question_for_human` as a single **closed**
question with the options named. It goes to a person, so it must be answerable in one line.

## The second product

Every `undecidable` is recorded. The accumulated list is the most useful feedback this system
produces about the project's documentation: it is exactly the set of questions the documentation
cannot answer. A run of ten arbitrations with zero `undecidable` on a thinly-documented project
does not mean the project is well documented — it means you were inventing rationales.
