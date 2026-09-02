# `.claude/settings.json` — rationale

One row per entry actually present in the file. Keep it in sync: a permission nobody can explain
is a permission nobody should have granted.

**Nothing here names a stack, a host, or a repository.** Toolchain commands come from
`.claude/.ai-worker/project-profile.yml`, resolved at run time. That is what makes this folder
droppable into any project.

`project-bootstrap` may **narrow** this file for a specific project — adding the stack's test
runner and package manager to `allow`, adding project-specific protected paths to `deny`. It must
never widen the deny list. Anything removed from `deny` is a decision a human makes in the
console, recorded on the project, and shown in the run report.

## Hooks

| Entry | Why it's here |
|---|---|
| `PreToolUse` → `Edit\|Write\|MultiEdit` → `scope-guard.sh` | Blocks a write outside the current task's worktree and any write to a protected path (CI config, `.git/config`, `.env*`, this settings file, the hooks). The `deny` globs cover the common spellings; the hook reads the actual resolved path, which is what a symlink or a `../` escape defeats. |
| `PreToolUse` → `Bash(git commit*)` → `secret-scan.sh` | Scans the **staged** diff for credential material — `gitleaks` when installed, otherwise the patterns in `security-patterns.yaml`. Commit time is the last point where a real token is distinguishable from a fixture by a human. |
| `PreToolUse` → `Bash(git push*)` → `pre-push-guard.sh` | Never push to the default branch, never force-push, never push a branch that is behind its own remote (the phantom-revert case, where a push silently undoes commits somebody already landed). |
| `PreToolUse` → `gh pr create` / `glab mr create` → `pr-create-guard.sh` | Draft-first, and — on GitLab — the project's source-branch-deletion convention. A non-draft pull request means a full pipeline run on every intermediate commit, which is the client's money. |
| `Stop` → `stop-verify.sh` | The live gate: formatter, linter, type check and the project's own test command, resolved per language from the profile. Blocks on red so a turn cannot end on a broken tree. A cheap no-op when nothing relevant changed, and an advisory rather than a block when the toolchain is unknown. |

Every hook carries a loop guard: none can block twice in a row, so a false positive cannot trap
a session.

## Permissions — `allow`

Only read-oriented and repository-local tooling is allowed by default: `git` (read, branch,
worktree, commit, push), text tools, and `gitleaks`. **The stack's own commands are added by
`project-bootstrap`** from the detected toolchain — a template cannot know whether this project
runs `pytest`, `npm test`, or `./gradlew test`, and guessing produces either a permission prompt
in the middle of every run or a command that does not exist.

## Permissions — `deny`

| Entry | Why |
|---|---|
| `sudo`, `rm -rf /`, `rm -rf ~` | ordinary blast-radius limits |
| `git push --force`, `-f` | destroys the history a review was based on, and silently invalidates the revision an approval was bound to |
| `git checkout main/master` | the worker works in a task branch; landing on the default branch is how an accidental commit gets there |
| `gh pr merge`, `glab mr merge`, `gh release`, `git tag` | merging and releasing are human decisions, always |
| `gh pr review`, `glab mr approve` | the worker cannot approve work — its own or anyone's |
| `env`, `printenv` | a debugging affordance that is also a credential-read primitive |
| `curl`, `wget` | arbitrary network egress. Legitimate needs go through the project's package manager, which bootstrap adds explicitly |
| `.env*` read/write | credentials live in the process environment, never in a file the model can open |
| CI config, `.git/config` | changing the pipeline changes what "verified" means. CI edits happen only in `ci-bootstrap` mode, where the diff is checked to contain nothing else |
| `.claude/settings.json`, `.claude/hooks/**` | a guard that can rewrite its own rules is not a guard |

The last row is the one to defend hardest in review. Every other entry has a plausible "just
this once" story; this one is what stops the others from being edited away.

---

# Narrowing for agent-desk

This file arrived with `project-template/` in the ai-worker repository. Everything above describes
the template. What follows is what this project changed, and why — the template's own rule is that
narrowing is allowed and widening is a decision a human records.

## Added to `deny`

```
Read(~/.claude/.credentials.json)     Read(~/.claude/sessions/*.key)
Edit(~/.claude/**)                    Write(~/.claude/**)
```

…each also in its `//home/...` absolute form, because a permission rule that only matches one
spelling of a path is a permission rule with a bypass.

This is the mechanism behind [`docs/07-security.md`](../docs/07-security.md), and it exists because
of a shape specific to this project: **the credential files sit beside the files this tool is
built to read.** `~/.claude/sessions/` holds `<pid>.json`, which is the board's backbone, and
`<pid>.<hash>.key`, which authenticates that session's messaging socket. Same directory, same
stem, mode `600`.

A single careless glob — `sessions/*` where `sessions/*.json` was meant — reads an authentication
key into a process whose entire job is to render things on a page. Nothing else in the system would
notice. The `Edit`/`Write` denials cover the other direction: this tool observes `~/.claude/`, and
a program that can write there can change the state it is reporting on.

## Added to `allow`

`make`, `poetry`, `pytest`, `ruff`, `mypy`, `scripts/*`, `gh pr *` — this project's own toolchain,
so the gate does not stop for a prompt on every turn.

## Not changed

The template's `deny` list is kept whole, including `curl` and `wget`. This process makes no
outbound network calls at all ([`docs/07-security.md`](../docs/07-security.md)), so an egress
command in a session working on it is worth a prompt.

`scope-guard.sh` still protects `.claude/settings.json` and `.claude/hooks/**`. A guard that can
rewrite its own rules is not a guard.
