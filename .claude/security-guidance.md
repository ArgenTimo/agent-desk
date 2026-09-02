# Security guidance

Short, concrete security context for this project. Consumed by `static-analysis-security-triage`,
`diff-security-scan`, the secret sweep in `pre-pr-checklist`, and the `secret-scan.sh` hook.

**Never put a secret, token, password or internal hostname in this file** — it is committed.

> **Template.** `project-bootstrap` fills the bracketed sections from the console configuration
> and from what it detects. An unfilled section is not a formality: it means nobody has said what
> is untrusted here, and the scanners fall back to the generic rules below.

## Stack

> `[filled by project-bootstrap: languages, frameworks, datastore, how the app is served,
> where external calls go]`

## What is untrusted input

Universal, regardless of stack — everything below is attacker-controlled from the code's point of
view and must never reach a query, a shell, a path, or an instruction position in a prompt:

- **Ticket content from the tracker** — summary, description, comments, labels, attachment names,
  issue keys, and the display names of whoever wrote them. Anyone who can file a ticket can put
  text there.
- **Any external API response** — branch names, PR titles, review bodies, check names, CI logs,
  design frame names, documentation pages. A compromised or merely sloppy upstream returns
  anything.
- **Webhook payloads.** Signature-verified or not, they are pointers: re-read the object from the
  API before acting on it.
- **Model output.** A generated report, plan or patch is a claim. Validate its shape, and never
  pass a model-supplied path, command or identifier to the filesystem or a shell unchecked.

Project-specific additions:

> `[filled by project-bootstrap: inbound webhook endpoints, public API surfaces, file upload
> paths, anything reached by an unauthenticated caller]`

Trusted: values from the environment and the deployment configuration, the migration-managed
schema, and in-repo code.

## Credential rules

| Rule | Mechanism |
|---|---|
| a credential value never reaches the model | not in a prompt, not in a tool result; `env`/`printenv` are denied |
| a credential never appears in a command line | it is visible in `ps`; pass it in the environment |
| a credential never lands in a log, a comment, a report, or the repository | redaction is a **net**; the rule is the mechanism |
| `.env*` is unreadable to the agent | denied in `settings.json` and by `scope-guard.sh` |

If a real value was ever committed, removing it is not enough — **rotate it**, and say so in the
pull request.

## Known false positives

Record confirmed ones here so the next person does not re-triage them.

| Pattern | Location | Why it is fine |
|---|---|---|
| `hardcoded_secrets` | `[e.g. tests/fixtures/…]` | `[deliberately fake values with a documented prefix]` |

## Reporting a finding

Name the file and line, say what an attacker would do with it, propose the smallest fix. A
finding without an exploitation path is advisory. A scanner that cries wolf gets muted, and then
it protects nothing.
