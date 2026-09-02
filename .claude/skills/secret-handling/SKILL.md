---
name: secret-handling
description: Where a credential may live, how it reaches the process, and every path it must never take — argv, a log, a comment, a report, a repository, a prompt. ACTIVATE when touching configuration, an integration, logging, or anything that spawns a subprocess, and whenever the phrase "just for now" appears near a token. Triggers on "store the token", "секреты", "add credentials". MUST NOT treat redaction as the primary defence, and MUST NOT leave a committed credential merely deleted rather than rotated.
metadata: {scope: project, author: ai-worker}
user-invocable: true
disable-model-invocation: false
---

## Where a credential may be

| Place | Allowed |
|---|---|
| a secret manager, or an encrypted store with the key held elsewhere | yes |
| the process environment, injected at start | yes |
| in memory, briefly, in the component that uses it | yes |
| a command-line argument | **no** — visible in `ps` to every user on the host |
| a file in the repository, including a fixture and a test config | **no** |
| a log line, an error message, a ticket comment, a report | **no** |
| a prompt or a tool result | **no** |

The agent cannot read `.env*` here by policy and by `scope-guard.sh`. That is deliberate: a
config file the agent can open is a credential store the agent can leak.

## Subprocesses

Pass secrets in the child's environment, never in its argv. Check what a library does before
trusting it — several popular clients accept a token as a positional argument and cheerfully put
it in the process table.

## Redaction is a net

Implement it at the logger, never at the call site: a call-site rule requires every future
contributor to remember it. But it catches only the values it was told about. The mechanism is
that credentials never enter those paths at all.

## When one is committed

Deleting the line is not enough — the value is in the history, in every clone, in every fork, and
in whatever mirror the CI provider keeps. **Rotate it**, then remove it, then say so in the pull
request. A rotated credential costs an afternoon; an un-rotated one is a live key on the internet
with a plausible story attached.

## Adding a new integration

1. The scopes requested are the **minimum the code actually uses**, listed and justified.
2. The credential's shape is added to `.claude/security-patterns.yaml` so the scanners recognise
   it.
3. It is validated at configuration time, not on first use — an invalid credential should fail
   when a human is present, not inside an unattended run at two in the morning.
4. The documentation names the scopes. A scope the code requests and the docs do not mention is a
   scope nobody agreed to.
