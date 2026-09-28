"""A transcript that no longer looks like the recording says so on the board (B2, docs/adr/0004).

The registry has a version to compare; a transcript line has one too, but the question that
matters is whether the lines still carry what the reader reads. Two signals: most of the window is
of line types nobody has seen, or a type the reader reads has lost a key it reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agent_desk.observe import transcript

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SESSION = "11111111-2222-4333-8444-555555555555"


def _recorded() -> list[dict[str, Any]]:
    return [json.loads(line) for line in (FIXTURES / "transcript.jsonl").read_text().splitlines()]


def _write(root: Path, lines: list[dict[str, Any]]) -> Path:
    where = root / "-home-someone-a-project"
    where.mkdir(parents=True)
    (where / f"{SESSION}.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return root


def test_the_recording_itself_has_not_drifted(tmp_path: Path) -> None:
    tail = transcript.read_tail(SESSION, root=_write(tmp_path, _recorded()))

    assert tail is not None
    assert tail.read_lines == len(_recorded())
    assert tail.drift is None


def test_a_key_the_reader_reads_going_missing_is_named(tmp_path: Path) -> None:
    lines = _recorded()
    for line in lines:
        if line["type"] == "assistant":
            line.pop("timestamp")

    tail = transcript.read_tail(SESSION, root=_write(tmp_path, lines))

    assert tail is not None and tail.drift is not None
    assert "assistant.timestamp" in tail.drift


def test_a_window_of_types_nobody_has_seen_is_drift_not_a_quiet_session(tmp_path: Path) -> None:
    """Every line renamed: nothing readable, and the tail still comes back to say why."""
    lines = [{**line, "type": f"{line['type']}-v2"} for line in _recorded()] * 3

    tail = transcript.read_tail(SESSION, root=_write(tmp_path, lines))

    assert tail is not None and tail.entries == []
    assert tail.drift is not None and "100%" in tail.drift


def test_a_few_new_types_among_known_ones_are_not_drift(tmp_path: Path) -> None:
    """The CLI adds line types all the time (sixteen at 2.1.283); a handful is not a format change."""
    lines = _recorded() * 3 + [{"type": "something-new", "sessionId": SESSION}] * 2

    tail = transcript.read_tail(SESSION, root=_write(tmp_path, lines))

    assert tail is not None and tail.drift is None


def test_the_board_says_it_once_for_every_session_that_shows_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_desk.observe.model import RegistryRead, Session
    from agent_desk.web import routes

    lines = _recorded()
    for line in lines:
        if line["type"] == "assistant":
            line.pop("message")
    root = _write(tmp_path, lines)
    registry_entry = json.loads((FIXTURES / "registry_entry.json").read_text())
    sessions = [
        Session.model_validate({**registry_entry, "pid": pid, "sessionId": SESSION})
        for pid in (1, 2)
    ]
    monkeypatch.setattr(routes.registry, "read_registry", lambda: RegistryRead(sessions=sessions))
    real = transcript.read_tail
    monkeypatch.setattr(routes.transcript, "read_tail", lambda sid: real(sid, root=root))
    monkeypatch.setattr(routes.registry, "resident_bytes", lambda pid: None)

    _, notices = routes.board()

    assert [notice for notice in notices if "assistant.message" in notice] == [notices[-1]]
