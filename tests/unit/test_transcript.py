"""The transcript tail, against the recorded lines rather than an idea of them."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from agent_desk.observe import transcript

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SESSION_ID = "00000000-0000-4000-8000-000000000001"


def _projects(tmp_path: Path, slug: str = "-a-directory-whose-name-is-lossy") -> Path:
    """A projects root holding the recorded transcript under an arbitrary directory name."""
    root = tmp_path / "projects"
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{SESSION_ID}.jsonl").write_text((FIXTURES / "transcript.jsonl").read_text())
    return root


@pytest.mark.unit
def test_the_recorded_tail_gives_the_board_its_row(tmp_path: Path) -> None:
    tail = transcript.read_tail(SESSION_ID, root=_projects(tmp_path))
    assert tail is not None
    assert tail.title == "Docker client for the supervisor"
    assert tail.last_prompt == "<prompt text>"
    assert tail.git_branch == "feature/docker-client"


@pytest.mark.unit
def test_a_sidechain_is_not_what_the_session_is_doing(tmp_path: Path) -> None:
    """v1 reads the main chain: a subagent's tool calls are noise on this board (docs/03)."""
    tail = transcript.read_tail(SESSION_ID, root=_projects(tmp_path))
    assert tail is not None
    assert [e.role for e in tail.entries] == ["user", "assistant", "user"]
    assert not any("subagent" in e.text for e in tail.entries)


@pytest.mark.unit
def test_an_assistant_entry_names_the_tool_and_not_the_command(tmp_path: Path) -> None:
    """ "The last action taken" is answered by the tool name; the command is the terminal's."""
    tail = transcript.read_tail(SESSION_ID, root=_projects(tmp_path))
    assert tail is not None
    assistant = next(e for e in tail.entries if e.role == "assistant")
    assert "[Bash]" in assistant.text
    assert "<command>" not in assistant.text
    assert assistant.at is not None


@pytest.mark.unit
def test_the_file_is_found_by_session_id_and_not_by_a_slug_from_cwd(tmp_path: Path) -> None:
    """docs/03: the slug is not invertible, so the reader never constructs one.

    Here the directory holding the transcript is named after nothing in particular, and a decoy
    directory named the way a `cwd` transform would name it holds somebody else's session.
    """
    root = _projects(tmp_path, slug="-home-dev-Project-Zomboid-My-Mods")
    decoy = root / "-home-dev-projects-example"
    decoy.mkdir()
    (decoy / "00000000-0000-4000-8000-000000000002.jsonl").write_text("")

    tail = transcript.read_tail(SESSION_ID, root=root)
    assert tail is not None
    assert tail.title == "Docker client for the supervisor"


@pytest.mark.unit
def test_the_same_session_in_two_directories_reads_the_one_being_written(tmp_path: Path) -> None:
    root = _projects(tmp_path, slug="-old-location")
    stale = root / "-old-location" / f"{SESSION_ID}.jsonl"
    fresh_dir = root / "-current-location"
    fresh_dir.mkdir()
    fresh = fresh_dir / f"{SESSION_ID}.jsonl"
    fresh.write_text(
        json.dumps({"type": "ai-title", "aiTitle": "the current one", "isSidechain": False}) + "\n"
    )
    os.utime(stale, (1, 1))

    tail = transcript.read_tail(SESSION_ID, root=root)
    assert tail is not None
    assert tail.title == "the current one"


@pytest.mark.unit
def test_no_transcript_is_not_an_error(tmp_path: Path) -> None:
    """docs/02, failure posture: that session shows registry facts only, marked as such."""
    assert transcript.read_tail(SESSION_ID, root=tmp_path / "projects") is None


@pytest.mark.unit
def test_a_line_torn_by_a_write_in_progress_is_skipped(tmp_path: Path) -> None:
    root = _projects(tmp_path)
    path = root / "-a-directory-whose-name-is-lossy" / f"{SESSION_ID}.jsonl"
    with path.open("a") as handle:
        handle.write('{"type": "assistant", "uuid": "a9", "mess')

    tail = transcript.read_tail(SESSION_ID, root=root)
    assert tail is not None
    assert tail.title == "Docker client for the supervisor"
    assert len(tail.entries) == 3


@pytest.mark.unit
def test_only_the_tail_is_read(tmp_path: Path) -> None:
    """A transcript reaches tens of megabytes; the board needs the last handful of lines."""
    root = tmp_path / "projects"
    directory = root / "-big"
    directory.mkdir(parents=True)
    line = {
        "type": "assistant",
        "isSidechain": False,
        "gitBranch": "main",
        "message": {"role": "assistant", "content": [{"type": "text", "text": ""}]},
    }
    with (directory / f"{SESSION_ID}.jsonl").open("w") as handle:
        for index in range(400):
            line["message"]["content"][0]["text"] = f"entry-{index:03d} " + "x" * 900
            handle.write(json.dumps(line) + "\n")

    tail = transcript.read_tail(SESSION_ID, root=root, lines=5, max_bytes=8000)
    assert tail is not None
    # The window bounds the read; `lines` bounds what a row shows. Both ends are asserted: the
    # last five entries of four hundred, and nothing from the beginning of the file.
    assert [entry.text.split()[0] for entry in tail.entries] == [
        f"entry-{index}" for index in ("395", "396", "397", "398", "399")
    ]


@pytest.mark.unit
def test_a_pasted_file_does_not_reach_the_template_whole(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    directory = root / "-huge-paste"
    directory.mkdir(parents=True)
    (directory / f"{SESSION_ID}.jsonl").write_text(
        json.dumps(
            {
                "type": "user",
                "isSidechain": False,
                "message": {"role": "user", "content": "y" * 50_000},
            }
        )
        + "\n"
    )
    tail = transcript.read_tail(SESSION_ID, root=root)
    assert tail is not None
    assert len(tail.entries[0].text) == transcript._MAX_ENTRY_CHARS
