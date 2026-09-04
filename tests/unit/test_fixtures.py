"""The fixtures are readable and carry the fields the board is specified to show.

This is the version check of docs/adr/0004 in its smallest useful form: it fails on the day a
re-recorded fixture arrives without a field the specification promises, which is one step before
the parser silently starts returning None for it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent_desk.observe.model import RECORDED_CLI_VERSION

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

# docs/03-session-observation.md, "The registry". Every one of these is rendered on the board or
# used to decide whether the session is alive; a fixture missing one is a specification drift.
REQUIRED_REGISTRY_FIELDS = {
    "pid",
    "procStart",  # liveness that survives pid reuse
    "sessionId",
    "cwd",
    "name",
    "status",
    "kind",
    "version",
    "updatedAt",
}


@pytest.mark.unit
def test_registry_fixture_carries_every_field_the_board_needs() -> None:
    entry = json.loads((FIXTURES / "registry_entry.json").read_text())
    missing = REQUIRED_REGISTRY_FIELDS - set(entry)
    assert not missing, f"registry fixture is missing {sorted(missing)} — re-record it"
    # Three values were recorded at 2.1.251 and 2.1.258, and a fourth — `waiting` — was seen at
    # 2.1.259 (docs/03-session-observation.md). The set is what that document records; a fifth
    # arriving in a recording should fail here and be read by a human before it reaches the board.
    assert entry["status"] in {"idle", "busy", "shell", "waiting"}


@pytest.mark.unit
def test_the_headless_fixture_is_the_shape_the_board_skips() -> None:
    """Recorded from a live `claude -p` this program started (tests/fixtures/README.md).

    Two properties are load-bearing and neither is obvious: `kind` says `interactive` even for a
    headless run, so it is not the discriminator — `entrypoint` is; and there is no `status` at
    all, which is why requiring one would have dropped these entries loudly instead of quietly.
    """
    entry = json.loads((FIXTURES / "registry_entry_headless.json").read_text())
    assert entry["entrypoint"].startswith("sdk-")
    assert entry["kind"] == "interactive"
    assert "status" not in entry
    assert "updatedAt" not in entry


@pytest.mark.unit
def test_transcript_fixture_covers_the_line_types_v1_reads() -> None:
    lines = [
        json.loads(line)
        for line in (FIXTURES / "transcript.jsonl").read_text().splitlines()
        if line.strip()
    ]
    types = {line["type"] for line in lines}
    assert {"ai-title", "last-prompt", "user", "assistant"} <= types

    # The board headline comes from ai-title (docs/03-session-observation.md).
    assert any(line.get("aiTitle") for line in lines if line["type"] == "ai-title")

    # gitBranch is what makes the board legible across worktrees of one repository.
    assert any(line.get("gitBranch") for line in lines)

    # v1 reads the main chain and skips subagent work; the fixture must contain one to skip.
    assert any(line.get("isSidechain") for line in lines)


@pytest.mark.unit
def test_the_recorded_stream_is_the_shape_the_answer_engine_reads() -> None:
    """The only fixture with no shape test, and it is the one the answer engine parses.

    It carries the CLI version it came from, like the other three, and a `rate_limit_event` line
    that v1 does not read — the line nobody would have invented, and the reason this directory
    holds recordings rather than examples (docs/adr/0004).
    """
    lines = [
        json.loads(line)
        for line in (FIXTURES / "stream_json.jsonl").read_text().splitlines()
        if line.strip()
    ]
    types = [line["type"] for line in lines]

    assert types[0] == "system"
    assert "assistant" in types
    assert "result" in types
    assert "rate_limit_event" in types
    system = next(line for line in lines if line["type"] == "system")
    assert system["claude_code_version"] == RECORDED_CLI_VERSION
    result = next(line for line in lines if line["type"] == "result")
    assert result["is_error"] is False


@pytest.mark.unit
def test_no_fixture_carries_a_real_identifier() -> None:
    """Scrubbing is part of recording, not a step someone remembers (tests/fixtures/README.md)."""
    for path in FIXTURES.glob("*"):
        if path.name == "README.md":
            continue
        text = path.read_text()
        assert "/home/skotwind" not in text, f"{path.name} keeps a real path"
        assert "PycharmProjects" not in text, f"{path.name} keeps a real path"
