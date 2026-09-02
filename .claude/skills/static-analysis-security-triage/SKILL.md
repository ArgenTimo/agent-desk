---
name: static-analysis-security-triage
description: Run the project's static analysis and the pattern scan against a change, then separate a real finding from a shape that merely resembles one. ACTIVATE when the diff touches authentication, input handling, data access, subprocess use, deserialization, cryptography or configuration, and in `pre-pr-checklist`. Triggers on "security scan", "триаж находок", "run sast". MUST NOT block on a pre-existing finding unrelated to the diff, and MUST NOT print a matched credential value.
metadata: {scope: project, author: ai-worker, adapted_from: internal security triage practice}
user-invocable: true
disable-model-invocation: false
---

## Scope: this change

Not an audit of the application. The question is **what could this diff have introduced**. A
project-wide review is a separate, human-commissioned exercise; running one per ticket produces a
wall of findings nobody reads, and the wall is how the real finding gets missed.

## What to run

```
<toolchain.<lang>.sast>                        # from the profile; null → needs_toolchain
gitleaks detect --no-banner --redact           # secrets across the branch range
grep -E -f <patterns from .claude/security-patterns.yaml> <changed files>
```

Read `.claude/security-guidance.md` first — it carries this project's trust boundaries and its
recorded false positives. Add to it when you confirm a new one; the next person should not
re-triage the same fixture.

## Triage

| Result | Action |
|---|---|
| true positive introduced by this diff | **blocking** |
| true positive in pre-existing code | advisory: report it, do not fix it in this ticket |
| false positive | note it in `security-guidance.md` with the reason |

For each real finding: the file and line, **what an attacker would do with it**, and the smallest
fix. A finding with no exploitation path is advisory — a scanner that cries wolf gets muted, and
then it protects nothing.

## The three categories worth extra attention

**Credential leak paths.** A token reaching a log, a comment, a report or an argv element. The
commit that introduces one is almost always "let me add a debug log".

**Injection reached by external data.** Ticket text, API responses, branch names and file names
are attacker-controlled. Reaching a query, a shell, a path or a raw-HTML sink with any of them is
a defect regardless of how unlikely the path looks.

**Authorization on a new surface.** A new route, handler or query that does not apply the check
its neighbours apply. Static analysis rarely finds this one; read for it deliberately.

## Redaction

Never print a matched secret — redact to a few characters. If a real value was ever committed,
removing it is insufficient: rotate it, and say so in the pull request.
