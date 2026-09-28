"""Open pull requests of the repositories somebody named, as one line each on the board (B3).

"PR: N open, the oldest X days" — the question a person otherwise answers with `gh pr list` in a
terminal. Read-only (tracker/github.py writes nothing), from a loop of its own that runs whether
or not this console has hands (A6): reading is what the board is for. Every five minutes, because
a pull request that has waited three days does not need to be seen within two seconds, and GitHub
counts requests.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog

from agent_desk.config import settings
from agent_desk.tracker import github

log = structlog.get_logger()

REFRESH_SECONDS = 300.0

# What each named repository said last time it was read. In memory: it is five minutes old at most
# and cheap to read again, so a restart loses nothing worth a table.
latest: dict[str, github.Read] = {}


def repos() -> list[str]:
    return [one.strip() for one in settings.pull_repos.split(",") if one.strip()]


async def run() -> None:
    """Read every named repository, then wait. A failed read is a line on the board, not a crash."""
    while True:
        for repo in repos():
            try:
                latest[repo] = await asyncio.to_thread(
                    github.open_pulls, repo, settings.github_token_env
                )
            except Exception:
                log.exception("pulls.read_failed", repo=repo)
        await asyncio.sleep(REFRESH_SECONDS)


def _days(created_at: str, now: datetime) -> int | None:
    try:
        opened = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (now - opened).days)


def lines(now: datetime | None = None) -> list[str]:
    """One sentence per named repository, in the order they were named."""
    now = now or datetime.now(UTC)
    said: list[str] = []
    for repo in repos():
        read = latest.get(repo)
        if read is None:
            said.append(f"PR · {repo}: not read yet")
        elif not read.ok:
            said.append(f"PR · {repo}: could not be read — {read.detail}")
        elif not read.pulls:
            said.append(f"PR · {repo}: none open")
        else:
            count = (
                f"{len(read.pulls)}+" if len(read.pulls) >= github.MOST_PULLS else len(read.pulls)
            )
            ages = [d for d in (_days(one.created_at, now) for one in read.pulls) if d is not None]
            oldest = f", oldest {max(ages)} day{'' if max(ages) == 1 else 's'}" if ages else ""
            said.append(f"PR · {repo}: {count} open{oldest}")
    return said
