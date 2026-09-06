"""Pull requests waiting on somebody, read as blockers (docs/adr/0010).

"В качестве блокеров также могут висеть PR с github, которые ожидают ревью/апрува/мержа — для тех
проектов, которые подключили гитхаб как коннектор."

Which is exactly right, and it is the same shape as the Jira reader for the same reasons. A pull
request that has been open for three days waiting on a review is a thing that has stopped, it is
stopped on a *person*, and it is invisible from a board that only watches sessions.

Read-only, and narrowly:

- **Only where somebody named a credential.** A GitHub link with no token variable is a link
  (`connectors.py`), and this refuses rather than reaching for an ambient one — the same rule
  `tracker/jira.py` follows and for the same reason.
- **Only open pull requests**, and only what says who they are waiting for: a review that was
  asked for and not given, a check that failed, a conflict.
- **Nothing is written.** No review, no comment, no merge, no label. The one door out of this
  program remains docs/adr/0005's, and it goes to a tracker rather than here.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from agent_desk import secrets as kept
from agent_desk.tracker.jira import TIMEOUT_SECONDS

# How many are read. A repository with two hundred open pull requests has a different problem, and
# a blockers column is not where it gets solved.
MOST_PULLS = 30


@dataclass(frozen=True)
class Pull:
    """One pull request that is waiting on somebody."""

    number: int
    title: str
    url: str
    waiting_for: str
    draft: bool = False

    @property
    def key(self) -> str:
        return f"#{self.number}"


@dataclass(frozen=True)
class Read:
    ok: bool
    pulls: tuple[Pull, ...] = ()
    detail: str = ""


def repo_of(url: str) -> str:
    """`owner/name` from a GitHub link, or an empty string.

    Both shapes somebody has in their clipboard: the page and the clone URL.
    """
    said = url.strip().removesuffix(".git").rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if said.startswith(prefix):
            parts = said[len(prefix) :].split("/")
            if len(parts) >= 2 and all(parts[:2]):
                return f"{parts[0]}/{parts[1]}"
    return ""


def waiting_for(pull: dict[str, object]) -> str:
    """Who or what this pull request is waiting on, in its own terms.

    Only what the response actually says. "Waiting for review" is a fact when a reviewer was
    requested and has not answered; "probably needs a look" would be a guess, and a blockers
    column full of guesses is one nobody reads (CLAUDE.md, rule five).
    """
    if pull.get("draft"):
        return "still a draft — its author has not asked for anything yet"
    reviewers = pull.get("requested_reviewers")
    if isinstance(reviewers, list) and reviewers:
        who = [
            str(one.get("login")) for one in reviewers if isinstance(one, dict) and one.get("login")
        ]
        return "waiting for a review from " + ", ".join(who[:3]) if who else "waiting for a review"
    if pull.get("mergeable_state") == "dirty":
        return "waiting for a conflict to be resolved"
    return "open and waiting to be merged"


def read_pulls(raw: bytes) -> tuple[Pull, ...]:
    """The pull requests in one response. A shape it does not recognise yields none."""
    try:
        found = json.loads(raw)
    except ValueError:
        return ()
    if not isinstance(found, list):
        return ()

    pulls: list[Pull] = []
    for one in found[:MOST_PULLS]:
        if not isinstance(one, dict):
            continue
        number = one.get("number")
        title = str(one.get("title", "")).strip()
        if not isinstance(number, int) or not title:
            continue
        pulls.append(
            Pull(
                number=number,
                title=title[:200],
                url=str(one.get("html_url", "")),
                waiting_for=waiting_for(one),
                draft=bool(one.get("draft")),
            )
        )
    return tuple(pulls)


def _get(url: str, authorization: str) -> tuple[int, bytes]:
    """One read. Https only, checked here rather than trusted from three functions away."""
    if not url.startswith("https://"):
        raise ValueError(f"refusing a request that is not https: {url.split(':', 1)[0]}:…")
    request = urllib.request.Request(  # noqa: S310  # nosec B310 — the scheme is checked above
        url,
        method="GET",
        headers={
            "Authorization": authorization,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(  # noqa: S310  # nosec B310 — same
            request, timeout=TIMEOUT_SECONDS
        ) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def open_pulls(repo: str, token_env: str) -> Read:
    """The open pull requests on one repository. Never raises, for the same reason `read_board`
    does not: this is reached from a loop that has to carry on either way."""
    if not repo:
        return Read(False, detail="that link does not name a GitHub repository")
    secret = kept.get(token_env)
    if not secret:
        return Read(
            False,
            detail=f"{token_env} is not set — export it, or type the token on the project's link",
        )

    query = urllib.parse.urlencode({"state": "open", "per_page": str(MOST_PULLS)})
    try:
        status, raw = _get(f"https://api.github.com/repos/{repo}/pulls?{query}", f"Bearer {secret}")
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        # The reason, never the request: the request carries an Authorization header.
        return Read(False, detail=f"could not reach GitHub: {type(exc).__name__}")

    if status != 200:
        return Read(False, detail=f"GitHub answered {status}")
    pulls = read_pulls(raw)
    if not pulls and not raw.strip().startswith(b"["):
        return Read(False, detail=f"GitHub answered {status} with a body this does not understand")
    return Read(True, pulls=pulls)
