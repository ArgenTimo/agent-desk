---
name: ci-bootstrap
description: Proposes a minimal CI pipeline for a project that has none, as a draft pull request whose diff touches ONLY CI configuration. Runs in `ci-bootstrap` mode, on an explicit human command (`ai:ci:bootstrap`), never automatically. Triggers only in that mode. MUST NOT touch any non-CI path, MUST NOT add deployment, release or publishing steps, MUST NOT invent a test command when the profile does not have one, and MUST NOT assume the pull request will be merged or build anything on top of it.
metadata:
  scope: project
  author: ai-worker
user-invocable: false
disable-model-invocation: false
---

## When this runs

Only when a human asked. A project without CI is common precisely among the teams most
interested in this service, and the correct response is an offer, not an action: a system that
can write its own verification is a system that can weaken it.

## What to produce

The smallest pipeline that yields a real verdict on a pull request: install, build if the stack
needs one, test. Nothing else.

Cost controls belong in the **first** version, because they are far harder to add after the bill
arrives:

| Control | Why |
|---|---|
| path filters | a documentation-only pull request must not run a build |
| concurrency cancel-in-progress | a new push cancels the superseded run |
| job timeouts | a hung process must not drain a quota |
| cheap job before expensive | a syntax error must not reach a paid runner |

If the stack has expensive runners (macOS, GPU), make the expensive job depend on the cheap one
explicitly rather than trusting ordering.

## Hard constraints

- **CI files only.** The diff may touch the workflow directory and, where the stack requires it,
  a lockfile or test configuration. Any other path fails the sentinel's diff check, correctly.
- **No secrets.** If the tests need one, leave a named placeholder and list it in the report
  under `requires_from_human`.
- **No invented commands.** If `detected.ci.test_cmd` and `toolchain.<lang>.test` are both null,
  report `blocked` and say the pipeline cannot be written until someone names the command.
  Guessing produces a pipeline that is green because it runs nothing.

## Report

```json
{
  "outcome": "finished|blocked",
  "pr_number": 12,
  "pipeline": {"triggers": ["pull_request"],
               "jobs": [{"name": "test", "runs": "pytest -q", "timeout_minutes": 15}],
               "cost_controls": ["path filters", "concurrency cancel", "timeouts"]},
  "not_included": ["deployment", "release", "version matrix"],
  "requires_from_human": ["a value for TEST_DATABASE_URL"],
  "next": "human review and merge"
}
```

Until such a pipeline exists and is merged, every report for this project must state that no
independent verification was available and that the local gate was the only check. The local
gate is never silently substituted for CI.
