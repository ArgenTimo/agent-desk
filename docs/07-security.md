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

**And it did not reach the one process that most needed it.** The headless run that answers a block
is started with `--restricted`, which — in the CLI's own words — "ignores user, project and local
settings files (managed settings and `--settings` still apply)". So the deny list above was off for
the single process on this machine that reads observed repositories, with `Read` pre-approved, over
every directory `--add-dir` hands it. Verified by execution rather than by reading: a canary
planted in an observed repository's `.env` came back verbatim inside the answer.

`agent_desk/answer/session.py` therefore passes the same denials to every run on the command line,
where `--restricted` cannot switch them off. Re-run against the same canary, the file is not
merely refused — it is not there.

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

**A page you are merely visiting must not be able to act on the console.** Loopback and the `Host`
check both let one through: a form on any website can post to `http://127.0.0.1:8787/blocks`
without asking CORS for permission, and the request carries the right `Host` because it really is
going there. Nothing secret is attached and nothing secret is needed — submitting a question,
discarding an idea and pressing send on the one write path are all just posts. So a state-changing
request whose `Sec-Fetch-Site` says it came from another page is refused. A request with no fetch
metadata is not a browser: it is a script run by the same operating-system user, who can already
read `~/.claude/` and needs no form.

**One outbound network call, and it is drawn narrowly.** For most of this program's life there
were none — the `claude` CLI makes its own, and this tool made none at all. Filing an idea in Jira
([adr/0005](adr/0005-one-door-out-to-a-tracker.md)) is the exception, and every clause of it is a
limit: one host, named in a link a human typed on a project card; one request, made only when
somebody clicks the second of two buttons; one payload, the ticket draft that person had already
read. No polling, no retry, no read back, and no other destination.

**A token can be typed into the console, and it stays on the machine it was typed on.** The first
answer to this was to refuse the field, and that was the wrong shape of no: somebody with a
console open wants to paste a token into it, and telling them to export a shell variable instead
is telling them to do the same thing in a less convenient place. What was actually wrong was
*where it went* — into the SQLite file a second application serves a view out of, and back onto a
page.

So there are two fields and the difference between them is the whole of it. **The name** is stored
with the project, in the database, and looks like `JIRA_TOKEN`: upper snake and short, which is
what every environment variable looks like and what no token does — the obvious rule, "letters,
digits and underscores", accepts a GitHub token verbatim. **The token** goes to
`~/.local/share/agent-desk/secrets.json`, mode 0600 in a 0700 directory, written by this program
and opened by nothing that answers a network request. It never comes back to a screen: the panel
can say *set here* or *not set*, which is what somebody needs to know, and there is no route that
returns a value and no template that could render one. A variable of the same name exported in the
shell wins over the file, so an operator with a secret manager is not quietly shadowed.

The credential is **not in the database** and not in this program's memory beyond the request that
uses it. `project_link.token_env` records the *name* of
the variable; the value is read at the moment of the request from the two places named above — the
shell first, then this machine's own file — and passed straight into it, and nothing logs it: a
network failure reports the exception type and the host, never the call. What the database never
holds is the token itself, because a token in a SQLite file with no encryption, in the process that
also serves a page to other people, is exactly the thing this page exists to refuse.

## Phase 4, where the model changed

The paragraph above holds for the console and stops holding the moment anything is served to
somebody else. That day arrived, and this is what replaced it — decided once, deliberately, rather
than arriving as a side effect of adding a login form.

**Two applications, two binds, one process.** The console keeps loopback and keeps everything: the
board, the input field, the blocks, the inbox with its context and drafts, and the one write path.
The shared view is a *separate* ASGI application with two routes, served on its own port, which
imports neither `observe` nor `peer` and therefore cannot reach a board or a session however it is
called. A single application deciding per request whether a viewer may see the board would work,
and would be one bad branch away from not working.

**It is off unless somebody says otherwise.** `share_host` is empty by default, the second
application is not constructed, and nothing is on the network. `make share SHARE_HOST=…` is a
sentence a human types, and typing it is the moment this model becomes the one in force. Bind it
to one interface rather than to all of them.

**A named link per viewer.** 256 bits from the system generator, stored as a hash and shown once —
so this database leaking is not the same event as the links leaking, and a lost link is replaced
rather than recovered.

That sentence was false for as long as this feature existed, and the place it was false is worth
recording. A viewer's token is a path segment, and the default access log of the server writes the
path: `"GET /shared/-rEm7_kLxJydW1is3YcDIVf2_PeTYFMU4boZhuus_oE HTTP/1.1" 200` — observed, not
inferred — beside the structured line naming the viewer. The store went to real trouble to keep
only a hash, and the log kept the token, in the artefact most likely to be tailed, piped, or pasted
into a bug report. **This process therefore runs with no request log at all** — not the shared bind alone, because
`access_log=False` is not a property of one server: the library implements it by stripping the
handlers off one process-wide logger, so two servers fight and the last one to load wins. It is
switched off explicitly, after every server is built, and a test asserts it. The minted token is
rendered into a response rather than carried through a redirect, because a query string is browser
history. What is logged about a viewer is their name and how many ideas they saw. Revocation is a timestamp rather than a delete, because the question an
audit asks is "who could see this, and until when". Every open is logged by viewer name and idea
count, never by content. A wrong link, a revoked link and a console that is not ready all answer
identically: a viewer learns whether their own link works and nothing else.

**The disclosure decision.** The shared page shows the summary, the text, the state and the date.
Not the project, not the branch, not the session's generated title, not the drafts, and never a
block. The context an idea carries is what makes it legible to its owner a week later — and it is
also a list of what that person was working on, including work a teammate has no business seeing.

**Every idea it renders is scrubbed on the way out**, including the human's own words. The store
keeps those verbatim on purpose ([05-ideas.md](05-ideas.md)); the rule that a surface a second
person can open redacts before it renders is about this page, and the two are not in conflict
because they are two different readers. The viewer's own name is not scrubbed — the owner typed it
into the mint form, and it is the one string on that page they wrote themselves.

**Neither surface can be framed.** A form submitted from inside an `iframe` of this console carries
`Sec-Fetch-Site: same-origin`, because it does — so the defence against a foreign page does nothing
about a foreign page wearing this one as a frame. Both applications answer `X-Frame-Options: DENY`,
`frame-ancestors 'none'` and `Referrer-Policy: no-referrer`, on every response including the ones
they refuse: the guard wraps each application from *outside* rather than sitting in its middleware,
because inside it a 500 answered with none of them — and a 500 is the response an attacker can most
easily provoke.

**The fail-open in that check is a loopback argument, and the shared bind is not loopback.** A
request with no fetch metadata on the console is a script run by the machine's owner; on the shared
bind it is a stranger, or a browser behind a proxy that strips `Sec-*` headers — which is exactly
the "unknown device" this page is for. It is left open deliberately: the token is in the path, so a
foreign page has nothing to submit *with*, and refusing the request would lock out the older
browsers this page exists to serve. Recorded here as a known cost rather than left as an assumption
somebody inherits.

**What it does not have, and the honest cost.** There is no TLS: the link travels in clear over
whatever network it is served on, so this belongs on a trusted LAN or behind a tunnel, and not on
the open internet. There are no accounts, no passwords and no sessions — the link *is* the
identity, which is why it is long, hashed, revocable and named after one person. One submission is
capped at 16 KB, counted as it arrives rather than read off a header a chunked request never sends;
the *number* of submissions is not capped, and a link holder who wanted to fill the owner's disk
one idea at a time could. Revocation is the answer to that, which is the same answer as for anyone
who abuses a link they were given.

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
- Never let a state-changing route answer a request a foreign page caused, and never move one to a
  `GET` where the guard does not apply.
- Never write a path under `~/.claude/` or under an observed repository.
- Never put transcript text into a log line, an error message, or a subprocess argument.
- Never pass a session's socket key to anything, including the peer-messaging client — that client
  reads it itself, from a path this code does not open.
