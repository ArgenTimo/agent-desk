"""The fixtures are readable and carry the fields the board is specified to show.

This is the version check of docs/adr/0004 in its smallest useful form: it fails on the day a
re-recorded fixture arrives without a field the specification promises, which is one step before
the parser silently starts returning None for it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    assert entry["status"] in {"idle", "busy", "shell"}


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
def test_no_fixture_carries_a_real_identifier() -> None:
    """Scrubbing is part of recording, not a step someone remembers (tests/fixtures/README.md)."""
    for path in FIXTURES.glob("*"):
        if path.name == "README.md":
            continue
        text = path.read_text()
        assert "/home/skotwind" not in text, f"{path.name} keeps a real path"
        assert "PycharmProjects" not in text, f"{path.name} keeps a real path"
