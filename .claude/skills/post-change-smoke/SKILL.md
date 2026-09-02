---
name: post-change-smoke
description: A fast check that the application still starts and its main surfaces respond after a change — the cheapest verification there is, and the one that catches an import error or a broken template that unit tests miss. ACTIVATE after a change touching application wiring, routing, templates, configuration or dependencies, when the project can be started locally. Triggers on "does it still run", "smoke test", "проверь что запускается". MUST NOT be reported as evidence that the feature works, and MUST NOT be attempted when the project has no runnable surface (`not_applicable`).
metadata: {scope: project, author: ai-worker, adapted_from: internal verification practice}
user-invocable: true
disable-model-invocation: false
---

## What it proves

That the process starts and its main entry points do not error. That is a low bar and an
extremely valuable one: a unit suite can be entirely green while the application fails to boot
because of an import cycle, a missing setting, a template that no test renders, or a dependency
that resolved differently.

It proves nothing about whether the feature is correct. Report it as a smoke check, never as
verification.

## The pass

1. Start the application the way the project documents it (the profile records the command; if it
   is null, this skill is `needs_toolchain`).
2. Hit the surfaces that matter: the health endpoint, the main route or command, one route the
   change touched, one it did not.
3. Watch the startup log for warnings that were not there before — a smoke pass reads the log, not
   just the status code.
4. Shut it down cleanly and confirm nothing is left running.

## For a non-HTTP project

The same idea in the project's shape: a CLI runs `--help` and one real subcommand; a library
imports cleanly in a fresh interpreter and instantiates its main entry point; a worker starts,
connects and processes one synthetic item.

## Reporting

```
Smoke: started clean, /healthz 200, /reports 200, /reports/export 200
       one new startup warning: deprecated config key `x` (pre-existing, unrelated)
Not verified: the export's contents — see the test suite
```

The last line is not modesty. A smoke pass that reads like verification is how a broken feature
ships behind a green report.
