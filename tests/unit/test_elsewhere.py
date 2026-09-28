"""Another executor's sessions are not on the board and their transcripts are not opened (task 21).

`aiworker_workspace_roots` defaults to ai-worker's project workspaces and its OS user's home. A
session, a job or a transcript under them is left out before anything about it is read.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from agent_desk.config import Settings
from agent_desk.observe import agents, elsewhere, jobs, registry, transcript
from agent_desk.observe.model import RegistryRead

pytestmark = pytest.mark.unit

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
THEIRS = "/srv/ai-worker/projects/client-a/.worktrees/AIWT-7"
SESSION = "11111111-2222-4333-8444-555555555555"


def _entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = json.loads((FIXTURES / "registry_entry.json").read_text())
    entry.update(overrides)
    return entry


def test_the_defaults_are_ai_workers_roots_and_nothing_near_them() -> None:
    assert elsewhere.elsewhere(THEIRS)
    assert elsewhere.elsewhere("/home/aiw")
    assert elsewhere.elsewhere("/home/aiw/ai-worker")
    assert not elsewhere.elsewhere("/home/aiwx/project")
    assert not elsewhere.elsewhere("/home/someone/agent-desk")
    assert not elsewhere.elsewhere("")


def test_no_roots_hides_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(elsewhere, "settings", Settings(aiworker_workspace_roots=""))

    assert not elsewhere.elsewhere(THEIRS)


def test_a_registry_entry_under_a_root_is_not_a_session_here(tmp_path: pathlib.Path) -> None:
    ours = _entry()
    theirs = _entry(pid=ours["pid"] + 1, cwd=THEIRS, sessionId=SESSION)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    for one in (ours, theirs):
        (sessions / f"{one['pid']}.json").write_text(json.dumps(one))
    proc = tmp_path / "proc"
    for one in (ours, theirs):
        stat = proc / str(one["pid"])
        stat.mkdir(parents=True)
        fields = ["S"] + ["0"] * 30
        fields[19] = one["procStart"]
        (stat / "stat").write_text(f"{one['pid']} (claude) " + " ".join(fields) + "\n")

    read = registry.read_registry(pattern=str(sessions / "*.json"), proc_root=proc)

    assert [one.cwd for one in read.sessions] == [ours["cwd"]]
    assert read.notices == []


def test_its_transcript_is_not_opened(tmp_path: pathlib.Path) -> None:
    recorded = (FIXTURES / "transcript.jsonl").read_text()
    theirs = tmp_path / "-srv-ai-worker-projects-client-a"
    theirs.mkdir()
    (theirs / f"{SESSION}.jsonl").write_text(recorded)

    assert transcript.read_tail(SESSION, root=tmp_path) is None

    ours = tmp_path / "-home-someone-a-project"
    ours.mkdir()
    (ours / f"{SESSION}.jsonl").write_text(recorded)
    assert transcript.read_tail(SESSION, root=tmp_path) is not None


def test_its_background_job_is_not_waiting_on_anybody_here(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "jobs"
    for short, cwd in (("aaaaaaaa", "/home/someone/a-project"), ("bbbbbbbb", THEIRS)):
        job = json.loads((FIXTURES / "job_state_blocked.json").read_text())
        (root / short).mkdir(parents=True)
        (root / short / "state.json").write_text(json.dumps({**job, "cwd": cwd}))
    monkeypatch.setattr(type(jobs.settings), "jobs_root", property(lambda self: root))

    assert [one.short_id for one in jobs.read_jobs().waiting] == ["aaaaaaaa"]


def test_the_cli_listing_it_is_not_a_complaint() -> None:
    """Left out of the registry, it must not come back as "listed with no registry file"."""
    said = agents.AgentsRead(
        agents=[agents.Agent(kind="interactive", sessionId=SESSION, cwd=THEIRS, status="busy")]
    )

    shown = agents.listed(RegistryRead(sessions=[]), said)

    assert shown.sessions == [] and shown.notices == []
