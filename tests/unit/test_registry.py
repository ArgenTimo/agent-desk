"""The registry reader, against the recorded entry rather than an idea of one.

The two tests that matter most here are the ones about a pid: a registry file is a claim about a
process, and a board that believes it shows a session that died an hour ago as `busy`
(docs/03-session-observation.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agent_desk.config import Settings
from agent_desk.observe import registry
from agent_desk.observe.model import RECORDED_CLI_VERSION

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = json.loads((FIXTURES / "registry_entry.json").read_text())
    entry.update(overrides)
    return entry


def _sessions_dir(tmp_path: Path, *entries: dict[str, Any]) -> str:
    directory = tmp_path / "sessions"
    directory.mkdir(exist_ok=True)
    for entry in entries:
        (directory / f"{entry['pid']}.json").write_text(json.dumps(entry))
    return str(directory / "*.json")


def _proc(tmp_path: Path, pid: int, starttime: str, comm: str = "claude") -> Path:
    """A /proc/<pid>/stat shaped like the real one: pid, comm in parens, then 50-odd fields."""
    root = tmp_path / "proc"
    entry = root / str(pid)
    entry.mkdir(parents=True, exist_ok=True)
    fields = ["S"] + ["0"] * 30
    fields[22 - 3] = starttime
    (entry / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields) + "\n")
    return root


@pytest.mark.unit
def test_the_recorded_version_matches_the_fixture() -> None:
    """The version check of docs/adr/0004 in one line.

    Re-recording a fixture without moving this constant would silence the banner the re-recording
    exists to raise.
    """
    assert json.loads((FIXTURES / "registry_entry.json").read_text())["version"] == (
        RECORDED_CLI_VERSION
    )


@pytest.mark.unit
def test_a_live_entry_becomes_a_session(tmp_path: Path) -> None:
    entry = _entry()
    read = registry.read_registry(
        pattern=_sessions_dir(tmp_path, entry),
        proc_root=_proc(tmp_path, entry["pid"], entry["procStart"]),
    )
    assert read.notices == []
    (session,) = read.sessions
    assert session.pid == entry["pid"]
    assert session.session_id == entry["sessionId"]
    assert session.status == "idle"
    assert session.name == entry["name"]
    assert session.updated_at == entry["updatedAt"]
    assert session.status_updated_at == entry["statusUpdatedAt"]
    # The project name comes from cwd, which is the only place it can come from: the transcript
    # directory is a lossy transform of it (docs/03-session-observation.md).
    assert session.project == "example"


@pytest.mark.unit
def test_a_dead_process_is_not_shown_and_is_not_a_problem(tmp_path: Path) -> None:
    entry = _entry()
    read = registry.read_registry(
        pattern=_sessions_dir(tmp_path, entry),
        proc_root=tmp_path / "empty-proc",
    )
    assert read.sessions == []
    assert read.notices == []


@pytest.mark.unit
def test_a_reused_pid_is_not_shown(tmp_path: Path) -> None:
    """The check that `procStart` exists for.

    The process is there and it is not the session: the operating system handed the number to
    something else. Without the second condition this row renders as a healthy `busy` session
    forever.
    """
    entry = _entry(procStart="10644")
    read = registry.read_registry(
        pattern=_sessions_dir(tmp_path, entry),
        proc_root=_proc(tmp_path, entry["pid"], "99999"),
    )
    assert read.sessions == []


@pytest.mark.unit
def test_liveness_survives_a_process_name_with_spaces_and_parentheses(tmp_path: Path) -> None:
    """`comm` is field 2 and it is not escaped, so splitting the whole line is wrong."""
    entry = _entry()
    proc = _proc(tmp_path, entry["pid"], entry["procStart"], comm="node (old) js")
    assert registry.is_alive(entry["pid"], entry["procStart"], proc_root=proc)


@pytest.mark.unit
def test_a_stat_file_that_cannot_be_read_is_not_alive(tmp_path: Path) -> None:
    """A pid whose /proc entry disappeared between the two checks is a session that ended."""
    proc = tmp_path / "proc"
    (proc / "15688").mkdir(parents=True)
    assert not registry.is_alive(15688, "10644", proc_root=proc)


@pytest.mark.unit
def test_a_key_file_beside_an_entry_is_never_opened(tmp_path: Path) -> None:
    """docs/07-security.md: the glob is `*.json`, never `*`.

    The `.key` here holds text that is not JSON, so a widened glob does not merely read an
    authentication key — it announces itself with a notice. Both halves of that are asserted.
    """
    entry = _entry()
    pattern = _sessions_dir(tmp_path, entry)
    (tmp_path / "sessions" / f"{entry['pid']}.4f3a.key").write_text("not-json-and-not-ours")
    read = registry.read_registry(
        pattern=pattern,
        proc_root=_proc(tmp_path, entry["pid"], entry["procStart"]),
    )
    assert len(read.sessions) == 1
    assert read.notices == []
    # And the pattern the program actually uses when nobody passes one.
    assert Settings(claude_home=tmp_path).registry_glob.endswith("*.json")


@pytest.mark.unit
def test_an_unreadable_entry_becomes_a_notice_rather_than_a_crash(tmp_path: Path) -> None:
    directory = tmp_path / "sessions"
    directory.mkdir()
    (directory / "1.json").write_text("{ this is not json")
    read = registry.read_registry(pattern=str(directory / "*.json"), proc_root=tmp_path / "proc")
    assert read.sessions == []
    assert len(read.notices) == 1
    assert "1.json" in read.notices[0]


@pytest.mark.unit
def test_a_field_that_moved_is_named(tmp_path: Path) -> None:
    """docs/adr/0004: one loud failure with a name on it, not five quiet Nones."""
    entry = _entry()
    del entry["status"]
    read = registry.read_registry(
        pattern=_sessions_dir(tmp_path, entry),
        proc_root=_proc(tmp_path, entry["pid"], entry["procStart"]),
    )
    assert read.sessions == []
    assert "status" in read.notices[0]


@pytest.mark.unit
def test_a_notice_carries_no_content_out_of_the_file(tmp_path: Path) -> None:
    """A notice is rendered on the board and may reach a log; the field name is enough."""
    entry = _entry()
    del entry["status"]
    read = registry.read_registry(
        pattern=_sessions_dir(tmp_path, entry),
        proc_root=_proc(tmp_path, entry["pid"], entry["procStart"]),
    )
    notice = read.notices[0]
    assert entry["cwd"] not in notice
    assert entry["sessionId"] not in notice


@pytest.mark.unit
def test_a_cli_newer_than_the_recording_raises_the_banner(tmp_path: Path) -> None:
    """Advisory, never a block: the session is still on the board (docs/adr/0004)."""
    entry = _entry(version="9.9.999")
    read = registry.read_registry(
        pattern=_sessions_dir(tmp_path, entry),
        proc_root=_proc(tmp_path, entry["pid"], entry["procStart"]),
    )
    assert len(read.sessions) == 1
    assert "9.9.999" in read.notices[0]
    assert RECORDED_CLI_VERSION in read.notices[0]


@pytest.mark.unit
def test_a_session_older_than_the_recording_does_not_raise_it(tmp_path: Path) -> None:
    """A banner that is always lit is a banner nobody reads.

    Sessions live for days, so an older one is always present after an update. An older shape that
    no longer fits the model raises its own notice naming the field, which is the specific signal;
    the version banner is for the direction the recording cannot have covered.
    """
    entry = _entry(version="2.1.100")
    read = registry.read_registry(
        pattern=_sessions_dir(tmp_path, entry),
        proc_root=_proc(tmp_path, entry["pid"], entry["procStart"]),
    )
    assert len(read.sessions) == 1
    assert read.notices == []


@pytest.mark.unit
def test_a_version_that_is_not_a_version_is_reported(tmp_path: Path) -> None:
    """Unknown is not evidence of sameness."""
    entry = _entry(version="dev-build")
    read = registry.read_registry(
        pattern=_sessions_dir(tmp_path, entry),
        proc_root=_proc(tmp_path, entry["pid"], entry["procStart"]),
    )
    assert "dev-build" in read.notices[0]


@pytest.mark.unit
def test_an_empty_registry_is_an_empty_board(tmp_path: Path) -> None:
    """docs/02-architecture.md, failure posture: empty is not an error."""
    read = registry.read_registry(pattern=str(tmp_path / "sessions" / "*.json"))
    assert read.sessions == []
    assert read.notices == []


def _headless(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = json.loads((FIXTURES / "registry_entry_headless.json").read_text())
    entry.update(overrides)
    return entry


@pytest.mark.unit
def test_a_programs_own_run_is_not_a_row_and_is_not_a_complaint(tmp_path: Path) -> None:
    """A headless `claude -p` registers itself, publishes no status, and is not a session a human
    triages — it is this program answering a question typed into it (docs/03-session-observation).

    Both halves matter. It must not appear on the board, and it must not raise the format banner:
    a warning that fires every time the tool is used is a warning nobody reads.
    """
    entry = _headless()
    read = registry.read_registry(
        pattern=_sessions_dir(tmp_path, entry),
        proc_root=_proc(tmp_path, entry["pid"], entry["procStart"]),
    )
    assert read.sessions == []
    assert read.notices == []


@pytest.mark.unit
def test_a_human_session_that_lost_a_field_is_still_a_complaint(tmp_path: Path) -> None:
    """The quiet skip above is for one recorded shape, not for anything missing a status."""
    entry = _entry()
    del entry["status"]
    read = registry.read_registry(
        pattern=_sessions_dir(tmp_path, entry),
        proc_root=_proc(tmp_path, entry["pid"], entry["procStart"]),
    )
    assert read.sessions == []
    assert "status" in read.notices[0]


@pytest.mark.unit
def test_a_headless_entry_beside_a_human_one_leaves_the_board_intact(tmp_path: Path) -> None:
    human = _entry()
    machine = _headless()
    pattern = _sessions_dir(tmp_path, human, machine)
    proc = _proc(tmp_path, human["pid"], human["procStart"])
    _proc(tmp_path, machine["pid"], machine["procStart"])

    read = registry.read_registry(pattern=pattern, proc_root=proc)
    assert [s.pid for s in read.sessions] == [human["pid"]]
    assert read.notices == []
