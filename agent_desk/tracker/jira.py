"""Create one issue in Jira, once, because a human pressed a button (docs/adr/0005).

Everything this module refuses to do is as much of its specification as what it does. It does not
read Jira, poll it, mirror a status back, update an issue or transition one. It does not retry. It
holds no credential: the link names the variable, the value is read at the moment of the request
from wherever the console keeps it, and this process only ever passes it straight into that one
request.

The transport is `urllib` from the standard library, in a thread. `httpx` is deliberately absent
from this project's dependencies, and a dependency added to reach one endpoint is a dependency in
the lock file forever (docs/adr/0003).
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from agent_desk import secrets as kept

# The link somebody typed is the URL they would paste from their browser, because that is the one
# they have: `https://acme.atlassian.net/browse/API`. The project key is the last segment, and it
# is validated rather than trusted — it is interpolated into a request body.
# The two shapes a person actually has in their clipboard. `/browse/DUCK` is the one somebody
# writes down; a board URL is the one the browser is showing them, and refusing it meant the
# integration sat unusable behind a link that looked right — which is what it did for a week.
_BROWSE = re.compile(r"\A(https://[A-Za-z0-9.\-]+(?::\d+)?)/browse/([A-Z][A-Z0-9_]{1,19})/?\Z")
_BOARD = re.compile(
    r"\A(https://[A-Za-z0-9.\-]+(?::\d+)?)/jira/(?:software|core)"
    r"(?:/c)?/projects/([A-Z][A-Z0-9_]{1,19})(?:/|\?|\Z)"
)

# How long one request is allowed to take. A console that hangs on somebody's tracker being slow
# is a console that hangs.
TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class Destination:
    """Where an idea would go: one site, one project key, one variable holding the credential."""

    site: str
    project_key: str
    token_env: str

    @property
    def browse(self) -> str:
        return f"{self.site}/browse/{self.project_key}"


@dataclass(frozen=True)
class Filed:
    """What came back. `key` is set when an issue exists, and `detail` says why when it does not."""

    filed: bool
    key: str = ""
    url: str = ""
    detail: str = ""


def destination_of(url: str, token_env: str | None) -> Destination | None:
    """The destination a link describes, or `None` when it does not describe one.

    A link with no token variable is a link, not a destination: this module refuses rather than
    reaching for an ambient credential, because a credential nobody named is a credential nobody
    decided to use here.

    Two URL shapes are accepted, and the second one is why this comment exists. `/browse/DUCK` is
    what somebody writes down; a *board* URL is what their browser is showing them when they copy
    it, and it names the same two facts — the site and the project key — in a different order. Only
    the first was matched, so a link that looked entirely correct produced no destination and the
    button never appeared, with nothing anywhere saying why.
    """
    if not token_env:
        return None
    trimmed = url.strip()
    match = _BROWSE.match(trimmed) or _BOARD.match(trimmed)
    if match is None:
        return None
    return Destination(site=match.group(1), project_key=match.group(2), token_env=token_env)


def _authorization(secret: str) -> str:
    """Jira Cloud wants `email:token` as Basic; a self-hosted PAT is a Bearer token.

    Which one is being held is decided by the shape of the value, because asking a human to also
    configure *which kind of credential they configured* is a setting that exists to be got wrong.
    """
    if ":" in secret:
        return "Basic " + base64.b64encode(secret.encode()).decode()
    return "Bearer " + secret


def _body(destination: Destination, summary: str, description: str) -> bytes:
    """The issue, in the shape the v3 API takes it. The description is Atlassian Document Format,
    and the one node type used is a paragraph: what is filed is the draft a human read, as text."""
    paragraphs = [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]}
        for line in description.split("\n\n")
        if line.strip()
    ]
    return json.dumps(
        {
            "fields": {
                "project": {"key": destination.project_key},
                "summary": summary[:255],
                "issuetype": {"name": "Task"},
                "description": {"type": "doc", "version": 1, "content": paragraphs},
            }
        }
    ).encode()


def _https_only(url: str) -> None:
    """Refuse anything that is not https, here rather than three functions away.

    The site always comes from `destination_of`, whose patterns require `https://`, so this cannot
    fire today. It is written anyway because what it protects against is somebody later building a
    URL from a different source and this file quietly following a `file://` into the filesystem
    with an Authorization header attached. A guarantee that lives next to the call is one that
    survives the call being edited.
    """
    if not url.startswith("https://"):
        raise ValueError(f"refusing a request that is not https: {url.split(':', 1)[0]}:…")


def _post(url: str, body: bytes, authorization: str) -> tuple[int, bytes]:
    """One request, and one of the two places in this program that open a socket to the network."""
    _https_only(url)
    request = urllib.request.Request(  # noqa: S310 — the scheme is checked by `_BROWSE`
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(  # noqa: S310  # nosec B310 — `_https_only` above
            request, timeout=TIMEOUT_SECONDS
        ) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def file_issue(destination: Destination, summary: str, description: str) -> Filed:
    """Create the issue. Blocking: the caller runs it in a thread (docs/adr/0003).

    Never raises. Every ending is a `Filed`, because this is reached from a route that has to
    render something either way, and an exception crossing that boundary would be a stack trace
    where an explanation belongs.
    """
    # Through `secrets`, not `os.environ`: a token typed on the project's link is kept on this
    # machine rather than exported, and the panel that says "set here" is reading the same two
    # places this does. Reading only the shell made the console report a credential it then could
    # not use (docs/07-security.md).
    secret = kept.get(destination.token_env)
    if not secret:
        return Filed(
            False,
            detail=f"{destination.token_env} is not set — export it, or type the token on the "
            "project's link",
        )

    try:
        status, raw = _post(
            f"{destination.site}/rest/api/3/issue",
            _body(destination, summary, description),
            _authorization(secret),
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        # The reason, never the request: the request carries an Authorization header.
        return Filed(False, detail=f"could not reach {destination.site}: {type(exc).__name__}")

    if status not in (200, 201):
        return Filed(False, detail=_why(status, raw))

    try:
        key = str(json.loads(raw)["key"])
    except (ValueError, KeyError, TypeError):
        return Filed(False, detail=f"Jira answered {status} with a body this does not understand")
    return Filed(True, key=key, url=f"{destination.site}/browse/{key}")


@dataclass(frozen=True)
class Ticket:
    """One issue read back from a tracker (docs/adr/0010).

    Four fields, and the omissions are the point. What this program does with a ticket is start
    work on it or show that it is stuck, and neither needs a reporter, a sprint, a story point or
    a component. Everything not named here is a field this console does not depend on and cannot
    be broken by.
    """

    key: str
    summary: str
    status: str = ""
    # What the ticket says about being stuck, in its own words, or empty. A quotation rather than
    # a judgement: "the ticket says it is blocked" is a fact with a source (CLAUDE.md, rule five).
    blocked_by: str = ""

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_by)


@dataclass(frozen=True)
class Read:
    """What one read found, or why it found nothing."""

    ok: bool
    tickets: tuple[Ticket, ...] = ()
    detail: str = ""


# Which statuses are worth pulling. `To Do` is the one the owner named; the rest of a board is
# either somebody's work in progress or done, and starting an agent on either is how two people
# end up doing the same thing.
WANTED_STATUSES = ("To Do", "Selected for Development", "Open", "Backlog")

# Words a ticket uses to say it is stuck. Matched in its own text and quoted back rather than
# interpreted — this program does not decide that a ticket is blocked, it repeats that it says so.
BLOCKED_WORDS = ("blocked", "blocker", "заблокирован", "блокер", "waiting on", "ждём", "ждем")

# How many are read at once. A board with four hundred tickets on it is a board this console
# should not be paging through: the queue takes one at a time anyway.
MOST_TICKETS = 50


def search_jql(destination: Destination) -> str:
    """Which issues to ask for. One project, unfinished, oldest first.

    Ordered by creation rather than by priority: priority on a board is a field people set at
    different times for different reasons, and "the one that has been waiting longest" is a rule
    that needs no agreement to be fair.
    """
    statuses = ", ".join(f'"{one}"' for one in WANTED_STATUSES)
    return f'project = "{destination.project_key}" AND status IN ({statuses}) ORDER BY created ASC'


def _text_of(field: object) -> str:
    """The words out of a Jira rich-text field, which is a document rather than a string.

    Depth-first over whatever is there, taking every `text` it finds. Deliberately incurious about
    the rest of the shape: this is used to quote a ticket back, so a node type nobody has seen
    contributes nothing rather than raising (docs/adr/0004, one layer down).
    """
    if isinstance(field, str):
        return field
    if isinstance(field, list):
        return " ".join(_text_of(one) for one in field)
    if isinstance(field, dict):
        said = str(field.get("text", "")) if isinstance(field.get("text"), str) else ""
        return " ".join(part for part in (said, _text_of(field.get("content"))) if part)
    return ""


def _blocked_by(fields: dict[str, object]) -> str:
    """What this ticket says about being stuck, quoted, or empty.

    It looks in the description and in the status name, and it never concludes anything from
    silence: a ticket that does not say it is blocked is a ticket this program says nothing about.
    """
    said = " ".join(
        part
        for part in (
            _text_of(fields.get("description")),
            _text_of(fields.get("status", {})),
        )
        if part
    ).strip()
    lowered = said.lower()
    if not any(word in lowered for word in BLOCKED_WORDS):
        return ""
    # The sentence it said it in, rather than the whole description.
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", said):
        if any(word in sentence.lower() for word in BLOCKED_WORDS):
            return sentence.strip()[:300]
    return said[:300]


def read_tickets(raw: bytes) -> tuple[Ticket, ...]:
    """The issues in one search response. A shape it does not recognise yields none.

    Never raises: this is on the path of a loop, and a tracker that answered something unexpected
    is a tracker this console reports as unreadable rather than one that stops the console.
    """
    try:
        found = json.loads(raw)
        issues = found["issues"]
    except (ValueError, KeyError, TypeError):
        return ()
    if not isinstance(issues, list):
        return ()

    tickets: list[Ticket] = []
    for issue in issues[:MOST_TICKETS]:
        if not isinstance(issue, dict):
            continue
        fields = issue.get("fields")
        fields = fields if isinstance(fields, dict) else {}
        status = fields.get("status")
        key = str(issue.get("key", "")).strip()
        summary = str(fields.get("summary", "")).strip()
        if not key or not summary:
            continue
        tickets.append(
            Ticket(
                key=key,
                summary=summary[:200],
                status=str(status.get("name", "")) if isinstance(status, dict) else "",
                blocked_by=_blocked_by(fields),
            )
        )
    return tuple(tickets)


def _get(url: str, authorization: str) -> tuple[int, bytes]:
    """One read. The second and last place in this program that opens a socket to the network."""
    _https_only(url)
    request = urllib.request.Request(  # noqa: S310 — the scheme is checked by `destination_of`
        url,
        method="GET",
        headers={"Authorization": authorization, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(  # noqa: S310  # nosec B310 — `_https_only` above
            request, timeout=TIMEOUT_SECONDS
        ) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def read_board(destination: Destination) -> Read:
    """The unfinished issues on one project's board (docs/adr/0010).

    Reading only: no transition, no comment, no assignment, no closing a ticket because an agent
    thinks it is done. The one write this program does is `file_issue`, unchanged.

    Never raises, for the same reason `file_issue` does not.
    """
    # The same two places `file_issue` reads, for the same reason: a token typed on the project's
    # link is kept on this machine rather than exported, and a reader that looked only at the
    # shell would report a credential the console had just been given as missing
    # (docs/07-security.md, and the exploration that found it in `file_issue`).
    secret = kept.get(destination.token_env)
    if not secret:
        return Read(
            False,
            detail=f"{destination.token_env} is not set — export it, or type the token on the "
            "project's link",
        )

    query = urllib.parse.urlencode(
        {
            "jql": search_jql(destination),
            "maxResults": str(MOST_TICKETS),
            "fields": "summary,status,description",
        }
    )
    try:
        status, raw = _get(f"{destination.site}/rest/api/3/search?{query}", _authorization(secret))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        # The reason, never the request: the request carries an Authorization header.
        return Read(False, detail=f"could not reach {destination.site}: {type(exc).__name__}")

    if status != 200:
        return Read(False, detail=_why(status, raw))
    tickets = read_tickets(raw)
    if not tickets and b'"issues"' not in raw:
        return Read(False, detail=f"Jira answered {status} with a body this does not understand")
    return Read(True, tickets=tickets)


def _why(status: int, raw: bytes) -> str:
    """What Jira said, trimmed to the part a human can act on.

    Its error bodies are `{"errorMessages": [...], "errors": {...}}`, and both halves matter: a
    missing issue type is in the second one and would otherwise render as an empty list.
    """
    try:
        problem = json.loads(raw)
        messages = list(problem.get("errorMessages") or [])
        messages += [f"{field}: {why}" for field, why in (problem.get("errors") or {}).items()]
    except ValueError:
        messages = []
    return f"Jira refused it ({status})" + (f": {'; '.join(messages)[:300]}" if messages else "")
