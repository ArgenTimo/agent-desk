"""Open pull requests of the named repositories, one line each on the board (B3).

Against a recorded GitHub response (tests/fixtures/github_pulls.json: three open pull requests of
ArgenTimo/agent-desk on 2026-09-27, bodies replaced).
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import UTC, datetime

import pytest
from agent_desk.config import Settings
from agent_desk.tracker import github
from agent_desk.web import pulls, routes

pytestmark = pytest.mark.unit

RECORDED = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "github_pulls.json"
).read_bytes()
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
def named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pulls, "settings", Settings(pull_repos="ArgenTimo/agent-desk, a/b"))
    monkeypatch.setattr(pulls, "latest", {})


def test_a_recorded_response_keeps_when_each_was_opened() -> None:
    read = github.read_pulls(RECORDED)

    assert [one.number for one in read] == [19, 10, 9]
    assert read[-1].created_at == "2026-09-10T13:54:00Z"


def test_each_named_repository_is_one_line_saying_how_many_and_how_old(named: None) -> None:
    pulls.latest["ArgenTimo/agent-desk"] = github.Read(True, pulls=github.read_pulls(RECORDED))
    pulls.latest["a/b"] = github.Read(False, detail="AGENT_DESK_GITHUB_TOKEN is not set")

    assert pulls.lines(NOW) == [
        "PR · ArgenTimo/agent-desk: 3 open, oldest 16 days",
        "PR · a/b: could not be read — AGENT_DESK_GITHUB_TOKEN is not set",
    ]


def test_not_yet_read_and_none_open_are_said_as_such(named: None) -> None:
    pulls.latest["a/b"] = github.Read(True, pulls=())

    assert pulls.lines(NOW) == ["PR · ArgenTimo/agent-desk: not read yet", "PR · a/b: none open"]


def test_a_full_page_is_said_as_at_least_that_many(named: None) -> None:
    """Only MOST_PULLS are read; saying exactly thirty of a hundred would be a wrong number."""
    one = github.read_pulls(RECORDED)[0]
    pulls.latest["ArgenTimo/agent-desk"] = github.Read(True, pulls=(one,) * github.MOST_PULLS)

    assert pulls.lines(NOW)[0].startswith(f"PR · ArgenTimo/agent-desk: {github.MOST_PULLS}+ open")


def test_nothing_named_is_nothing_read_and_nothing_said(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pulls, "settings", Settings(pull_repos=""))

    assert pulls.repos() == []
    assert pulls.lines(NOW) == []


async def test_the_loop_reads_every_named_repository_with_the_named_token(
    named: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[str, str]] = []

    def reader(repo: str, token_env: str) -> github.Read:
        asked.append((repo, token_env))
        return github.Read(True)

    async def stop(seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(pulls.github, "open_pulls", reader)
    monkeypatch.setattr(pulls.asyncio, "sleep", stop)

    with pytest.raises(asyncio.CancelledError):
        await pulls.run()

    assert asked == [
        ("ArgenTimo/agent-desk", "AGENT_DESK_GITHUB_TOKEN"),
        ("a/b", "AGENT_DESK_GITHUB_TOKEN"),
    ]
    assert set(pulls.latest) == {"ArgenTimo/agent-desk", "a/b"}


def test_the_board_carries_the_lines(named: None) -> None:
    pulls.latest["ArgenTimo/agent-desk"] = github.Read(True, pulls=github.read_pulls(RECORDED))

    page = routes.render_board()

    assert "PR · ArgenTimo/agent-desk: 3 open" in page
