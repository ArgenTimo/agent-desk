---
name: project-bootstrap
description: Adapter skill — the ONLY skill that writes project facts. Runs once when a project is onboarded to ai-worker, and again when the skillset is updated or a detection input changes. Detects stack, paths, runtime, test commands and CI from project files, merges the values supplied by the ai-worker console, and writes `.claude/.ai-worker/project-profile.yml` and `capabilities.yml` into the workspace. Every other skill in this folder reads those two files and hardcodes no path, URL, prefix or command. Runs NON-INTERACTIVELY — anything it cannot detect and the console did not supply is written as `null` and reported as an onboarding question, never guessed and never asked mid-run. Triggers when the profile is absent, when `AI_WORKER_BOOTSTRAP=1`, or on the phrase "bootstrap the project profile". MUST NOT activate when the profile exists and the input hash is unchanged (exit with one line), and MUST NOT activate mid-run in any other mode.
metadata:
  scope: project
  author: ai-worker
  adapted_from: spec-to-ship/workflow-bootstrap/project-bootstrap
user-invocable: true
disable-model-invocation: false
---

## What changed from the source skill

The original asked a human, in one batched dialog, for anything it could not detect. Inside
ai-worker there is no human in the session: the run is unattended, and a question asked here
would block a pipeline instead of a person. Three consequences:

1. **Console values win over detection.** The orchestrator passes the project configuration
   (repository, default branch, tracker key, status map, policy, permissions) in
   `AI_WORKER_PROJECT_CONFIG`. Those are facts a human already confirmed; do not re-detect them.
2. **Undetectable stays `null`.** Never guess a command. A `null` toolchain entry marks the
   dependent skill `needs_toolchain`; the skill then degrades to its generic methodology. A
   guessed `gradlew testFuzz` is a defect, a `null` is correct.
3. **Unresolved values are emitted as onboarding questions**, written to
   `.claude/.ai-worker/onboarding-questions.yml`. The console shows them to the operator. They
   never become questions on a client ticket — a client should never be asked which test runner
   we failed to detect.

## Outputs

```
.claude/.ai-worker/project-profile.yml       detected facts + console-supplied values
.claude/.ai-worker/capabilities.yml          per-skill readiness
.claude/.ai-worker/protected-paths.txt       extra paths scope-guard.sh must refuse
.claude/.ai-worker/onboarding-questions.yml  what neither detection nor the console resolved
```

Templates for the first two live beside them as `*.template.yml`. Start from those; they carry
the field-by-field comments explaining what a `null` means.

It also **narrows** `.claude/settings.json`: the detected package manager, test runner, formatter
and type checker are added to `permissions.allow`, because a template cannot know whether this
project runs `pytest`, `npm test`, or `./gradlew test`, and guessing produces either a permission
prompt in the middle of every run or a command that does not exist.

It may add to `permissions.deny` and to `protected-paths.txt`. It must **never remove** a deny
entry — that is a decision a human makes in the console, recorded on the project.

The location is fixed and project-relative. Plugins are copied to a cache directory, so a plugin
can never be a stable home for project state. Never reference these via `../` or relative to the
plugin's own location.

## Idempotency

Hash the detection inputs — dependency manifests, lockfiles, CI config, test config, the console
config blob. If the hash matches the one recorded in the profile and both files exist, print
`profile is up to date` and stop. Re-running on an unchanged project must cost seconds and write
nothing.

## Detection

| Source | Extract |
|---|---|
| dependency manifests / lockfiles | languages, frameworks, package managers (a project may be polyglot — record a list) |
| CI config | platform, pipeline file, and the **exact** test command the gate runs |
| test config | test roots (plural — some projects run over more than one) |
| directory tree | source, tests, e2e, migrations |
| `git remote` | code host, and which credential pair applies |
| `CLAUDE.md`, `CONVENTIONS.md`, `docs/adr/` | rule sources for `decision-arbitration` — record the paths |

That last row is new and matters: `decision-arbitration` can only cite documents it knows about,
and a project with no rule sources will produce a high `undecidable` rate. Record what exists;
do not invent a convention document.

## Toolchain resolution

Per detected language, resolve `test`, `test_changed`, `coverage`, `property_testing`, `e2e`,
`sast`, `api_contract` from the support matrix the source skill carries. Known mappings ship for
Python, JavaScript/TypeScript and Java; other languages are detected and asked. **Any cell you
cannot resolve is `null`.**

## Capabilities

```yaml
skills:
  local-gate:        {status: ready}
  result-review:     {status: ready}
  ci-bootstrap:      {status: ready, note: "no pipeline detected"}
  pr-lifecycle:      {status: ready}
  diff-security-scan:{status: needs_toolchain, missing: "toolchain.python.sast"}
```

`ready`, `needs_toolchain`, `needs_credentials`. A skill that is not ready says so at the top of
its output rather than silently doing half its job.

## Non-destructive

Never modifies source code, CI config, `.env`, or another skill. Never commits. The profile lives
in the workspace and is not part of the client's repository — a bootstrap run must leave
`git status` clean.
