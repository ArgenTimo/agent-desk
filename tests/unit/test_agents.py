"""`claude agents --json` decides which sessions are on the board; the registry fills in the rest (B7).

Against a recorded answer (tests/fixtures/claude_agents.json, 2.1.283), with identifiers replaced.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from agent_desk.config import Settings
from agent_desk.observe import agents
from agent_desk.observe.model import RegistryRead, Session

pytestmark = pytest.mark.unit

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
RECORDED = (FIXTURES / "claude_agents.json").read_text()


def _session(session_id: str, status: str = "idle") -> Session:
    entry: dict[str, Any] = json.loads((FIXTURES / "registry_entry.json").read_text())
    return Session.model_validate({**entry, "sessionId": session_id, "status": status})


def test_the_recorded_answer_reads_as_four_rows_of_two_kinds() -> None:
    said = agents.parse(RECORDED)

    assert said.agents is not None
    assert [one.kind for one in said.agents].count("interactive") == 3
    waiting = next(one for one in said.agents if one.status == "waiting")
    assert waiting.waiting_for == "permission prompt"
    assert next(one for one in said.agents if one.kind == "background").state == "blocked"


def test_an_answer_that_moved_is_a_notice_that_names_no_content() -> None:
    said = agents.parse('{"sessions": "secret text"}')

    assert said.agents is None
    assert "no longer reads as recorded" in said.notice
    assert "secret" not in said.notice


def test_the_cli_list_decides_the_rows_and_their_status() -> None:
    said = agents.parse(RECORDED)
    listed = "11111111-2222-4333-8444-555555555555"
    busy = "22222222-2222-4333-8444-555555555555"
    gone = "99999999-2222-4333-8444-555555555555"
    read = RegistryRead(sessions=[_session(listed), _session(busy, "idle"), _session(gone)])

    shown = agents.listed(read, said)

    assert [one.session_id for one in shown.sessions] == [listed, busy]
    assert shown.sessions[1].status == "busy"
    # The third interactive row has no registry file here: counted, not invented.
    assert shown.notices == [
        "1 session listed by `claude agents` had no registry file to read the rest from, "
        "and is not shown"
    ]


def test_a_cli_that_cannot_be_read_leaves_the_registry_board_and_says_so() -> None:
    read = RegistryRead(sessions=[_session("11111111-2222-4333-8444-555555555555")])

    shown = agents.listed(read, agents.AgentsRead(notice="claude is not installed here"))

    assert len(shown.sessions) == 1
    assert shown.notices == [
        "claude is not installed here — the board is read from ~/.claude/sessions alone"
    ]


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("#!/bin/sh\ncat '{recorded}'\n", None),
        ("#!/bin/sh\nexit 3\n", "exited 3"),
        ("#!/bin/sh\necho not json\n", "no longer reads as recorded"),
    ],
)
def test_the_command_is_run_and_each_way_it_fails_is_named(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, script: str, expected: str | None
) -> None:
    cli = tmp_path / "claude"
    cli.write_text(script.format(recorded=FIXTURES / "claude_agents.json"))
    cli.chmod(0o755)
    monkeypatch.setattr(agents, "settings", Settings(claude_bin=str(cli)))
    monkeypatch.setattr(agents, "_kept", None)

    said = agents.read_agents()

    if expected is None:
        assert said.agents is not None and len(said.agents) == 4
    else:
        assert said.agents is None and expected in said.notice


def test_the_answer_is_kept_between_redraws(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process per redraw is ~190 MB every two seconds."""
    count = tmp_path / "count"
    cli = tmp_path / "claude"
    cli.write_text(f"#!/bin/sh\necho x >> '{count}'\necho '[]'\n")
    cli.chmod(0o755)
    monkeypatch.setattr(agents, "settings", Settings(claude_bin=str(cli), agents_poll_seconds=60))
    monkeypatch.setattr(agents, "_kept", None)

    for _ in range(5):
        agents.read_agents()

    assert count.read_text().count("x") == 1


def test_a_missing_cli_is_named() -> None:
    import agent_desk.observe.agents as module

    said = module._run()

    assert said.agents is None and "is not installed here" in said.notice
