# `.claude/skills` — index

36 skills. Nothing here names a stack, a host or a repository: every command, path and convention
comes from `.claude/.ai-worker/project-profile.yml`, which **only `project-bootstrap` writes**.
That single rule is what makes this folder droppable into any project.

`.claude/.ai-worker/capabilities.yml` records each skill's readiness — `ready`,
`needs_toolchain`, `needs_credentials`, `not_applicable`. A skill that is not ready says so at the
top of its output instead of silently doing half its job.

## Delivery lifecycle

| Skill | Stage |
|---|---|
| `project-bootstrap` | onboarding — the only writer of project facts |
| `ticket-intake` | can this be started, and what is missing |
| `ticket-plan` | approach, files, a test per acceptance criterion |
| `decision-arbitration` | choosing between options, citing what justifies the choice |
| `implementation-loop` | the code, the commits, the draft pull request |
| `local-gate` | the project's own verification, run locally |
| `result-review` | judging the result before a human sees it |
| `correction-round` | fixing blocking findings, bounded |
| `pr-lifecycle` | the pull request, its description, its review threads |
| `tracker-report` | the report written back to the ticket |
| `ci-bootstrap` | a minimal pipeline for a project that has none |

## Engineering discipline

| Skill | Read when |
|---|---|
| `requirement-traceability` | before writing code — what does this change serve |
| `worktree-workflow` | any session that will produce a commit |
| `integration-adapter-contract` | code that calls an external system |
| `api-change-discipline` | adding or changing an endpoint |
| `schema-migration-safety` | a model change or a migration |
| `secret-handling` | configuration, integrations, subprocesses |
| `observability-discipline` | logging, metrics, error paths |
| `documentation-discipline` | the change made a documented statement false |

## Tests

| Skill | Read when |
|---|---|
| `requirements-based-tests` | writing any test |
| `generated-test-review` | after writing tests — the audit for model-written ones |
| `fakes-over-mocks` | a test that touches an external system |
| `test-data-management` | non-trivial setup, or tests interfering |
| `flaky-test-management` | a result differs between runs of one revision |
| `test-impact-selection` | iterating in a slow suite |
| `coverage-report-review` | reading a coverage report without misusing it |
| `property-based-testing` | parsers, encoders, transformations, "for any X" |
| `combinatorial-test-design` | three or more interacting parameters |
| `http-service-virtualization` | a test would otherwise hit a third party |

## Verification and release

| Skill | Read when |
|---|---|
| `qa-gate` | the change feels finished — five adversarial passes |
| `pre-pr-checklist` | before un-drafting or asking for review |
| `post-change-smoke` | wiring, routing, config or dependency changes |
| `ui-regression-review` | the diff touches a user interface |

## Security and policy

| Skill | Read when |
|---|---|
| `diff-security-scan` | every review; and before pushing an auth or input-handling change |
| `static-analysis-security-triage` | running the scanners and separating real findings from noise |
| `language-policy-guard` | only when the project declares a language policy |

## The rules these all obey

1. **Only `project-bootstrap` writes project facts.** Every other skill reads them.
2. **Unknown stays `null`.** A skill whose toolchain entry is null reports `needs_toolchain`,
   degrades to its generic methodology, and asks. It never guesses a command — a guessed test
   command produces a pipeline that is green because it ran nothing.
3. **A check that did not run is never reported as passed.** Skipped, unavailable and
   not-applicable are outcomes with names.
4. **Nothing approves its own work**, and nothing blocks on taste.

---

## In this repository

This folder is ai-worker's `project-template/` dropped into agent-desk unchanged, so everything
above describes the template rather than this project. Three things differ here, and each is a
consequence of agent-desk having no tracker, no clients and no pipeline
([`../../docs/adr/0001`](../../docs/adr/0001-a-separate-repository.md)).

**Rule 1 above has an exception here.** `project-bootstrap` is the only writer of project facts in
a project ai-worker manages, because a console configures it. Nothing configures this one, so
`.ai-worker/project-profile.yml` was **written by hand**, and `project-bootstrap` is marked
`not_applicable`. The rule that still holds, and is the one that matters, is the other half: every
skill and hook *reads* its commands from that file and hardcodes none.

**A third of these skills do not apply, and say so.** `.ai-worker/capabilities.yml` marks each one
— `ticket-intake`, `ticket-plan` and `tracker-report` have no tracker to read;
`http-service-virtualization` has no outbound call to virtualise. They are marked rather than
deleted, so an improvement made upstream still applies here as a patch. A skill that reports
`not_applicable` is doing its job; a skill that invents work to look busy is not.

**Where the rule sources are.** `decision-arbitration` and `requirement-traceability` cite
`rule_sources` from the profile, which here is `CLAUDE.md`, then `docs/`, then `design/`, then
`docs/adr/`. In this project those documents are the specification, not notes: present tense in
them is a requirement on the implementation.

## One verified gap in the harness

`secret-scan.sh` prefers `gitleaks` and falls back to `grep -E` over `security-patterns.yaml`.
`grep -E` is POSIX ERE and does not understand the `(?i)` inline flag — it warns and matches
nothing, and the hook sends that warning to `/dev/null`. On a machine without `gitleaks`, every
`(?i)` pattern in that file is therefore silently inert.

Found by testing the hook rather than by reading it: a staged
`AWS_SECRET_ACCESS_KEY = "wJalr…"` committed without complaint. POSIX-safe duplicates were added
for the two highest-value patterns and the rest are recorded in
[`../security-guidance.md`](../security-guidance.md) under "Known gaps".

**This applies to the upstream `project-template/` as well**, where the same file and the same
hook live unchanged.
