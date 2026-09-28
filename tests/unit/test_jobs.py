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
from agent_desk.observe.model import JOB_STATES, JobEnd

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


# --- B1: blocked and stopped, recorded at 2.1.267 / 2.1.273 --------------------------------------
@pytest.mark.unit
@pytest.mark.parametrize(
    ("fixture", "terminal", "failed", "waiting"),
    [
        ("job_state_blocked.json", False, False, True),
        ("job_state_stopped.json", True, True, False),
        ("job_state_running.json", False, False, False),
        ("job_state_working.json", False, False, False),
        ("job_state_done.json", True, False, False),
        ("job_state_failed.json", True, True, False),
    ],
)
def test_every_recorded_state_reads_as_what_the_cli_meant(
    fixture: str, terminal: bool, failed: bool, waiting: bool
) -> None:
    """`stopped` is over but not finished; `blocked` is waiting on a human and not over — it can
    be answered and carry on."""
    job = JobEnd.model_validate(json.loads((FIXTURES / fixture).read_text()))

    assert job.state in JOB_STATES
    assert (job.terminal, job.failed, job.waiting) == (terminal, failed, waiting)


@pytest.mark.unit
def test_a_blocked_job_says_what_it_needs_and_a_stopped_one_what_it_asked() -> None:
    blocked = JobEnd.model_validate(json.loads((FIXTURES / "job_state_blocked.json").read_text()))
    stopped = JobEnd.model_validate(json.loads((FIXTURES / "job_state_stopped.json").read_text()))

    assert blocked.needs and blocked.questions == 1
    assert stopped.block is not None and stopped.questions == len(stopped.block.questions) == 1


@pytest.mark.unit
def test_the_board_read_finds_the_waiting_jobs_and_names_a_state_it_has_not_seen(
    jobs_root: pathlib.Path,
) -> None:
    _job(jobs_root, "aaaaaaaa", "job_state_blocked.json")
    _job(jobs_root, "bbbbbbbb", "job_state_done.json")
    _job(jobs_root, "cccccccc", "job_state_stopped.json")
    (jobs_root / "dddddddd").mkdir()
    (jobs_root / "dddddddd" / "state.json").write_text(json.dumps({"state": "hibernating"}))

    read = jobs.read_jobs()

    assert [one.short_id for one in read.waiting] == ["aaaaaaaa"]
    assert len(read.notices) == 1
    assert "'hibernating'" in read.notices[0]


@pytest.mark.unit
def test_a_job_file_that_does_not_parse_is_a_notice_on_the_board(jobs_root: pathlib.Path) -> None:
    (jobs_root / "eeeeeeee").mkdir()
    (jobs_root / "eeeeeeee" / "state.json").write_text("{ not json")

    assert "could not be read" in jobs.read_jobs().notices[0]


@pytest.mark.unit
def test_the_board_says_how_many_are_waiting_and_how_to_answer_them(
    jobs_root: pathlib.Path,
) -> None:
    from agent_desk.web import routes

    _job(jobs_root, "aaaaaaaa", "job_state_blocked.json")
    _job(jobs_root, "ffffffff", "job_state_blocked.json")

    page = routes.render_board()

    assert "2 background jobs waiting on you" in page
    assert "claude attach aaaaaaaa" in page
    assert "what the job is waiting for, in its own words" in page
