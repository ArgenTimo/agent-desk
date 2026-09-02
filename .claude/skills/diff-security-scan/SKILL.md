---
name: diff-security-scan
description: 'Security skill — scan the change itself for the classes of defect a diff can introduce: secrets, injection through unvalidated input, broken authorization on a new path, unsafe deserialization, and dependencies added without cause. Runs the project''s SAST command when the profile has one. Read by the executor before pushing when the diff touches an auth, input-handling or data-access surface, and by the reviewer on every diff. Triggers on phrases "security check this change", "проверь на безопасность". MUST NOT be treated as a security review of the application, and MUST NOT block on generic advice unrelated to the diff.'
metadata:
  scope: project
  author: ai-worker
  adapted_from: spec-to-ship/appsec-review (ASVS/WSTG review + SAST triage), narrowed to a diff
user-invocable: true
disable-model-invocation: false
---

## Scope: this diff, not this application

The source skillset carried a full OWASP ASVS/WSTG review methodology. That is a project-level
exercise a human commissions, and running it on every ticket would produce a wall of findings
nobody reads. What survives here is the part that belongs on a change: **what could this diff
have introduced?**

## The checklist

| Class | Look for |
|---|---|
| **Secret in the diff** | keys, tokens, connection strings, `.env` content, a credential in a test fixture |
| **Injection** | user input reaching a query, a shell, a template, or a path without validation |
| **Authorization** | a new route, handler or query that does not apply the check its neighbours apply |
| **Data exposure** | a new response, log line or error message carrying more than the caller should see |
| **Unsafe deserialization** | untrusted input into pickle, YAML load, XML with entities enabled |
| **Dependency** | a package added — is it needed, is it maintained, does it pull in a tree |
| **Crypto** | hand-rolled anything, a hardcoded IV or salt, a weak default |

For each hit: name the file and line, say what an attacker would do with it, and propose the
smallest fix. A finding without an exploitation path is advisory, not blocking — a scanner that
cries wolf is a scanner that gets muted.

## SAST

When `toolchain.<lang>.sast` is set, run it **on the changed files** and triage:

| Result | Action |
|---|---|
| true positive in the diff | blocking finding |
| true positive in pre-existing code | advisory; report, do not fix in this ticket |
| false positive | note it and, if the project keeps suppressions, propose one with a reason and an owner |

When the entry is `null`, say `needs_toolchain` and do the manual checklist. Do not install a
scanner to satisfy the skill.

## Blocking bar

Only two things block from this skill: **a secret in the diff**, and a **new** vulnerability with
a concrete exploitation path introduced by these changes. Everything else is advisory. Security
findings that block on style teach a team to route around the check.
