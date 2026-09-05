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
import urllib.request
from dataclasses import dataclass

from agent_desk import secrets as kept

# The link somebody typed is the URL they would paste from their browser, because that is the one
# they have: `https://acme.atlassian.net/browse/API`. The project key is the last segment, and it
# is validated rather than trusted — it is interpolated into a request body.
_BROWSE = re.compile(r"\A(https://[A-Za-z0-9.\-]+(?::\d+)?)/browse/([A-Z][A-Z0-9_]{1,19})/?\Z")

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
    """
    match = _BROWSE.match(url.strip())
    if match is None or not token_env:
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


def _post(url: str, body: bytes, authorization: str) -> tuple[int, bytes]:
    """One request, and the only place in this program that opens a socket to the network."""
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
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
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
