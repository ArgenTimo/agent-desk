---
name: documentation-discipline
description: When a change must update documentation, and how to write the update so it stays worth trusting — checkable statements, decisions that carry their reason, and no rewriting a document to match code that violated it. ACTIVATE when a change alters documented behaviour, adds a decision worth recording, or leaves a document stale. Triggers on "update the docs", "напиши ADR", "document this". MUST NOT be used to rewrite a rule so that a violation of it becomes compliant.
metadata: {scope: project, author: ai-worker}
user-invocable: true
disable-model-invocation: false
---

## When a change must touch documentation

- It alters behaviour a document describes.
- It adds a rule others must follow.
- It makes an existing statement false.
- It resolves a question the documentation could not answer — especially one arbitration marked
  `undecidable`. Those are the highest-value documentation edits available, because each removes a
  real ambiguity somebody already hit.

Not every change needs a document. A bug fix that restores stated behaviour changes nothing about
what is stated.

## How to write it

- **A statement must be checkable.** "The API should be fast" is not one. "List endpoints return
  within 200 ms at p95 for pages of 50" is.
- **Carry the reason.** A rule without one gets deleted in six months by someone who cannot see
  why it exists — and they will be right to, because a rule nobody can justify is
  indistinguishable from an accident.
- **Name the mechanism, not just the guarantee.** "Only reviewers can merge" is true because of a
  branch-protection setting. Write the setting.
- **Say what is not covered.** A document that appears complete but is not is worse than an
  explicitly partial one.

## Decision records

For a decision with real alternatives — a library that will be hard to replace, a new process, a
boundary, a reversal of an earlier decision — record: the context, the decision, **the
alternatives with why each was rejected**, and the consequences **including the bad ones**. A
record that lists no rejected alternative documents a decision nobody stress-tested.

Not for naming choices.

## The thing this skill exists to prevent

Editing a document so that it agrees with code that violated it. If the code is right and the
document is stale, fix the document and say so in the commit message. If the code is wrong, fix
the code. If the trade-off itself is wrong, argue it in the pull request. What must not happen is
the quiet fourth option where the prose is adjusted and nobody notices a property was dropped.
