"""What became of a dispatched agent, read from the CLI's own job file.

Against fixtures recorded from two real jobs — one that died before its first turn and one that
worked and left a branch — because a hand-written one would encode what its author believed the
file looked like (docs/adr/0004).
"""

from __future__ import annotations

import json
import pathlib

import pytest
from agent_desk.observe import jobs

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


def _job(where: pathlib.Path, short_id: str, fixture: str) -> None:
    """A job directory shaped the way the CLI shapes it."""
    directory = where / short_id
    directory.mkdir(parents=True)
    (directory / "state.json").write_text((FIXTURES / fixture).read_text())


@pytest.fixture
def jobs_root(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    root = tmp_path / "jobs"
    root.mkdir()
    monkeypatch.setattr(type(jobs.settings), "jobs_root", property(lambda self: root))
    return root


@pytest.mark.unit
def test_an_agent_that_died_before_it_ran_says_so(jobs_root: pathlib.Path) -> None:
    _job(jobs_root, "11111111", "job_state_failed.json")

    ended = jobs.read_job("11111111")

    assert ended is not None
    assert ended.failed
    assert "Invalid worktree name" in ended.detail
    # It never got far enough to have one, and the fallback derivation is what settle then uses.
    assert ended.worktree_branch == ""


@pytest.mark.unit
def test_an_agent_that_worked_reports_its_branch_and_what_it_spent(
    jobs_root: pathlib.Path,
) -> None:
    _job(jobs_root, "66666666", "job_state_done.json")

    ended = jobs.read_job("66666666")

    assert ended is not None
    assert not ended.failed
    assert ended.state == "done"
    assert ended.worktree_branch == "worktree-a-name"
    assert ended.tokens == 17825


@pytest.mark.unit
def test_a_job_the_cli_has_tidied_away_is_silent_rather_than_broken(
    jobs_root: pathlib.Path,
) -> None:
    """`claude rm` removes the directory, and absence must not read as failure."""
    assert jobs.read_job("nothinghere") is None


@pytest.mark.unit
def test_a_file_that_no_longer_parses_is_silent_too(jobs_root: pathlib.Path) -> None:
    """A format that moved says nothing rather than something wrong (docs/adr/0004)."""
    (jobs_root / "77777777").mkdir()
    (jobs_root / "77777777" / "state.json").write_text("{ this is not json")
    assert jobs.read_job("77777777") is None

    (jobs_root / "88888888").mkdir()
    (jobs_root / "88888888" / "state.json").write_text(json.dumps({"tempo": "idle"}))
    assert jobs.read_job("88888888") is None


@pytest.mark.unit
def test_a_short_id_never_walks_out_of_the_jobs_directory(jobs_root: pathlib.Path) -> None:
    """It arrives from a database row, and a reader that follows `../..` on a bad one is a thing
    somebody has to think about later."""
    for bad in ("", ".", "..", "../../etc", "a/b"):
        assert jobs.read_job(bad) is None
        assert jobs_root in jobs.state_path(bad).parents


@pytest.mark.unit
def test_an_unknown_state_is_passed_through_rather_than_mapped(jobs_root: pathlib.Path) -> None:
    """A value this program has not seen must not silently become one it has."""
    (jobs_root / "99999999").mkdir()
    (jobs_root / "99999999" / "state.json").write_text(json.dumps({"state": "cancelled"}))

    ended = jobs.read_job("99999999")

    assert ended is not None
    assert ended.state == "cancelled"
    assert not ended.failed
