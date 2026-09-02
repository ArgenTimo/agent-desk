# Security guidance

Short, concrete security context for agent-desk. Consumed by `static-analysis-security-triage`,
`diff-security-scan`, the secret sweep in `pre-pr-checklist`, and the `secret-scan.sh` hook.

**Never put a secret, token, password or internal hostname in this file** — it is committed.

The long-form reasoning is [`docs/07-security.md`](../docs/07-security.md). This file is the
operational summary the scanners read.

## Stack

Python 3.12, FastAPI, SQLAlchemy 2.0 over SQLite, Jinja2 with HTMX and server-sent events. One
process, bound to `127.0.0.1`, started by hand with `make run`. No container, no daemon, no
database server, no JavaScript build step.

**This process makes no outbound network calls.** The `claude` CLI it spawns makes its own; this
code makes none. An `httpx`, `requests`, `urllib` or `curl` appearing in a diff is a finding, not
a dependency.

Data at rest: one SQLite file at `~/.local/share/agent-desk/agent-desk.db`, holding threads,
blocks, ideas and drafts. No credentials are stored anywhere by this program.

## What is untrusted input

Universal, regardless of stack — everything below is attacker-controlled from the code's point of
view and must never reach a query, a shell, a path, or an instruction position in a prompt:

- **Any external API response.** Branch names, PR titles, check names, CI logs.
- **Model output.** A generated summary, classification or answer is a claim. Validate its shape,
  and never pass a model-supplied path, command or identifier to the filesystem or a shell.

Specific to this project, and the part that matters most here:

- **Everything under `~/.claude/`.** Session names, `cwd`, `gitBranch`, the generated `aiTitle`,
  and every line of every transcript. These are written by other agents working on other
  repositories, and a transcript contains whatever those agents read — including a ticket someone
  else filed and a web page someone else wrote. It reaches this program as **data to render**,
  never as an instruction, a path to open, or an argument to a subprocess.
  ([`docs/03-session-observation.md`](../docs/03-session-observation.md))
- **The `POST /api/signal` body**, posted by a hook in an observed project. Verified or not, it is
  a pointer: re-read from the registry rather than trusting what it carries.
  A signal that arrives for an unknown session is discarded, not created.
- **Everything typed into the input field**, including by a viewer in Phase 4.

There is no public surface: the bind is loopback and there is no authentication, because anything
that can reach the port can already read `~/.claude/` as the same OS user. **That makes the
loopback bind load-bearing.** A change to `host` in `agent_desk/config.py` is a security change and
needs the Phase 4 work of [`docs/09-roadmap.md`](../docs/09-roadmap.md) with it.

Trusted: values from the environment, and in-repo code.

## Credential rules

| Rule | Mechanism |
|---|---|
| `~/.claude/.credentials.json` is never opened | denied in `settings.json`, both path spellings |
| `~/.claude/sessions/*.key` is never opened | denied in `settings.json`; the registry glob is `*.json`, asserted by `tests/unit/test_structure.py` |
| nothing writes under `~/.claude/` | `Edit`/`Write` denied in `settings.json` |
| a credential never appears in a command line | it is visible in `ps` |
| a transcript excerpt never reaches a log, an error message, or a subprocess argument | redaction runs at the store boundary, not in the template |
| `.env*` is unreadable to the agent | denied in `settings.json` and by `scope-guard.sh` |

The shape that makes this project unusual: **the credential files sit in the same directory as the
files the tool exists to read**, with the same stem. `sessions/<pid>.json` is the board's backbone;
`sessions/<pid>.<hash>.key` authenticates that session's messaging socket. One widened glob reads
an authentication key into a rendering process, and nothing else in the system would notice.

If a real value was ever committed, removing it is not enough — **rotate it**, and say so in the
pull request.

## Known gaps

Recorded so the next person does not rediscover them, and so no report claims a check that did not
run.

| Gap | Effect | Close it by |
|---|---|---|
| `gitleaks` is not installed on this machine | `secret-scan.sh` falls back to `grep -E` over `security-patterns.yaml`, which is narrower than gitleaks' rule set | installing `gitleaks` |
| `grep -E` does not understand the `(?i)` inline flag | every `(?i)` pattern in `security-patterns.yaml` matches nothing in the fallback path, and the hook sends grep's warning to `/dev/null` | POSIX-safe duplicates were added for the two highest-value patterns; the remaining four are inert without gitleaks |

The second one was found by testing the hook rather than by reading it: a staged
`AWS_SECRET_ACCESS_KEY = "wJalr…"` was committed without complaint. **It applies equally to the
upstream `project-template/` in the ai-worker repository**, which is where this file came from.

## Known false positives

Record confirmed ones here so the next person does not re-triage them.

| Pattern | Location | Why it is fine |
|---|---|---|
| identifier-shaped strings | `tests/fixtures/**` | recorded fixtures with every identifier replaced by zeros and every text field by a `<placeholder>`; `tests/unit/test_fixtures.py` asserts no real path survives |

## Reporting a finding

Name the file and line, say what an attacker would do with it, propose the smallest fix. A finding
without an exploitation path is advisory. A scanner that cries wolf gets muted, and then it
protects nothing.
