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
