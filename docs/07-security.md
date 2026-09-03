# Security

This tool reads the most sensitive directory on the machine and its whole purpose is to put what
it finds on a screen. Two threats follow, and they are not the usual web ones.

## 1. Credentials that sit next to what we read

`~/.claude/` holds, beside the state this tool wants:

| Path | What it is | Rule |
|---|---|---|
| `~/.claude/.credentials.json` | the account token | never opened |
| `~/.claude/sessions/*.key` | one per session, mode `600`, purpose unestablished | never opened |
| any `.env` in an observed repository | client credentials | never opened |

None of these is needed. The registry entries this tool reads are the `*.json` files; the `*.key`
files sit beside them with a matching pid prefix and mode `600`. **The glob is `sessions/*.json`,
never `sessions/*`** — a widened glob here reads a credential into a process whose entire job is to
render things.

**Corrected 2026-09-03.** This page used to say those key files authenticate a session's
peer-messaging socket. That was never verified and it appears to be wrong: the CLI's own schema
describes the connecting process as identified by the kernel — "read from the connection
(SO_PEERCRED / LOCAL_PEERPID) — never from the payload". What the files are for is not established
here, and the rule does not depend on knowing: they are credentials of some kind, nothing needs
them, and the one write path opens no file at all ([09-roadmap.md](09-roadmap.md), Phase 3).

The mechanism is `.claude/settings.json`, which denies these paths to any session working in this
repository. This paragraph explains the denial; it does not implement it. A rule that lives only in
prose is a wish.

## 2. Transcripts contain everything the agent saw

A transcript is the record of a working session: source code, command output, anything the human
pasted, and any secret that passed through either. Treating it as display-safe is wrong.

Three rules follow.

**Redaction runs at the store boundary, not in the template.** A view that forgets to call a filter
renders correctly and leaks. The tail of a transcript is redacted where it is read, once, and the
templates receive text that is already safe.

**The patterns are the ones the skillset already ships.** `.claude/security-patterns.yaml` came
with the template and is the same file the ai-worker repository uses. One source of secret shapes,
maintained in one place.

**Redaction is a net, not the mechanism.** It catches shapes it knows. The real protection is that
transcript content does not leave this machine and is not copied into a second store
([02-architecture.md](02-architecture.md)): the tool reads a tail on demand and renders it, and
keeps no copy.

## The exposure surface, deliberately small

Bound to `127.0.0.1`. No authentication in v1 and none needed: anything that can reach the port can
already read `~/.claude/` directly, because it is the same operating-system user. **The loopback
bind is therefore load-bearing, not a default** — the day it becomes `0.0.0.0`, the whole security
model of v1 is gone and the tool needs a real one.

**A browser is not a local process, and the loopback argument does not cover it.** Any page on the
open web can point a hostname of its own at `127.0.0.1`; the request then leaves the user's own
browser, and as far as that browser is concerned it is same-origin with this console. The reply
would be transcript text. So the application answers only to a `Host` header naming loopback and
refuses anything else before a route sees it — which is what makes the bind mean, for the one
client that is not a process on this machine, what the paragraph above says it means.

No outbound network calls. The `claude` CLI makes its own; this tool makes none.

## Phase 3, where the model changes

Problem 5 of [01-vision.md](01-vision.md) — a view for teammates who do not write code — is the
point at which every sentence above stops being sufficient. A second viewer means a network bind,
authentication, and per-viewer authorisation, and it means transcript excerpts reaching someone
with no access to the repository they came from.

That is why it is a phase of its own with an entry condition
([09-roadmap.md](09-roadmap.md)), and why the shared view starts as the ideas list only, with no
transcript surface at all. A board that shows branch names and generated titles is already a
disclosure decision; it should be made once, deliberately, and not arrive as a side effect of
adding a login form.

## For anyone changing this code

- Never widen `sessions/*.json`.
- Never widen the allowed `Host` list beyond loopback while there is no authentication.
- Never write a path under `~/.claude/` or under an observed repository.
- Never put transcript text into a log line, an error message, or a subprocess argument.
- Never pass a session's socket key to anything, including the peer-messaging client — that client
  reads it itself, from a path this code does not open.
