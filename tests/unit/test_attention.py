"""The one thing on this board that is inferred, and the order the board is sorted in.

docs/03-session-observation.md: "this session is waiting for me" is not on disk. It is derived
from silence, so every assertion here is about the inference being narrow, and about it carrying
the observation it was made from.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agent_desk.observe.model import (
    AttentionHint,
    Session,
    TailEntry,
    TranscriptTail,
    attention_hint,
    triage_rank,
)
from agent_desk.web.routes import _ago

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = 1_788_400_000_000
FIVE_MINUTES = 300


def _session(**overrides: Any) -> Session:
    entry: dict[str, Any] = json.loads((FIXTURES / "registry_entry.json").read_text())
    entry.update(overrides)
    return Session.model_validate(entry)


def _tail(role: str | None) -> TranscriptTail:
    entries = [TailEntry(role=role, text="…")] if role else []
    return TranscriptTail(session_id="s", entries=entries)


@pytest.mark.unit
def test_idle_with_the_last_word_from_the_assistant_is_the_inference() -> None:
    hint = attention_hint(
        _session(status="idle", statusUpdatedAt=NOW - 14 * 60_000),
        _tail("assistant"),
        now=NOW,
        after_seconds=FIVE_MINUTES,
    )
    assert hint.waiting
    assert hint.observation == "idle 14m · last entry: assistant"


@pytest.mark.unit
def test_the_flag_never_travels_without_its_observation() -> None:
    """A guessed status shown as a fact is worse than no status (CLAUDE.md, rule five)."""
    for status, last, since in (("busy", "assistant", 0), ("idle", "user", 60), ("shell", None, 0)):
        hint = attention_hint(
            _session(status=status, statusUpdatedAt=NOW - since * 60_000),
            _tail(last),
            now=NOW,
            after_seconds=FIVE_MINUTES,
        )
        assert hint.observation.startswith(status)


@pytest.mark.unit
def test_an_idle_session_the_human_spoke_to_last_is_not_waiting() -> None:
    """It was interrupted, or it has already been answered. Neither wants a flag."""
    hint = attention_hint(
        _session(status="idle", statusUpdatedAt=NOW - 60 * 60_000),
        _tail("user"),
        now=NOW,
        after_seconds=FIVE_MINUTES,
    )
    assert not hint.waiting


@pytest.mark.unit
def test_a_session_idle_for_ten_seconds_is_about_to_be_busy_again() -> None:
    hint = attention_hint(
        _session(status="idle", statusUpdatedAt=NOW - 10_000),
        _tail("assistant"),
        now=NOW,
        after_seconds=FIVE_MINUTES,
    )
    assert not hint.waiting


@pytest.mark.unit
def test_a_working_session_is_never_inferred_to_be_waiting() -> None:
    for status in ("busy", "shell"):
        hint = attention_hint(
            _session(status=status, statusUpdatedAt=NOW - 60 * 60_000),
            _tail("assistant"),
            now=NOW,
            after_seconds=FIVE_MINUTES,
        )
        assert not hint.waiting


@pytest.mark.unit
def test_a_session_with_no_transcript_read_is_never_flagged() -> None:
    hint = attention_hint(
        _session(status="idle", statusUpdatedAt=NOW - 60 * 60_000),
        None,
        now=NOW,
        after_seconds=FIVE_MINUTES,
    )
    assert not hint.waiting
    assert "no transcript entry read" in hint.observation


@pytest.mark.unit
def test_the_board_is_sorted_by_what_needs_a_human() -> None:
    """docs/06-console.md: inferred-waiting first, then working, then idle — never `updatedAt`."""
    waiting = AttentionHint(waiting=True, observation="idle 14m · last entry: assistant")
    quiet = AttentionHint(waiting=False, observation="—")

    ranks = [
        triage_rank(_session(status="idle"), waiting),
        triage_rank(_session(status="busy"), quiet),
        triage_rank(_session(status="shell"), quiet),
        triage_rank(_session(status="waiting"), quiet),
        triage_rank(_session(status="idle"), quiet),
    ]
    assert ranks[0] < ranks[1]
    assert ranks[1] == ranks[2]
    assert ranks[2] < ranks[3] < ranks[4]


@pytest.mark.unit
def test_a_status_this_program_does_not_know_is_not_treated_as_quiet() -> None:
    """A CLI update adding a fourth status must not hide the session at the bottom of the board."""
    unknown = triage_rank(
        _session(status="compacting"), AttentionHint(waiting=False, observation="")
    )
    idle = triage_rank(_session(status="idle"), AttentionHint(waiting=False, observation=""))
    assert unknown < idle


@pytest.mark.unit
def test_age_is_rendered_in_the_shortest_form_that_is_still_true() -> None:
    assert _ago(NOW - 120_000, NOW) == "2m ago"
    assert _ago(NOW - 3 * 3_600_000, NOW) == "3h ago"
    assert _ago(NOW - 2 * 86_400_000, NOW) == "2d ago"


@pytest.mark.unit
def test_under_a_minute_the_board_does_not_count_seconds() -> None:
    """A per-second number re-renders the page every second, which costs a text selection and an
    open row all day, and decides nothing (docs/06-console.md)."""
    assert _ago(NOW - 4_000, NOW) == "just now"
    assert _ago(NOW - 59_000, NOW) == "just now"
    assert _ago(NOW - 61_000, NOW) == "1m ago"


@pytest.mark.unit
def test_a_long_silence_is_read_in_hours_rather_than_minutes() -> None:
    hint = attention_hint(
        _session(status="idle", statusUpdatedAt=NOW - 3 * 3_600_000),
        _tail("assistant"),
        now=NOW,
        after_seconds=FIVE_MINUTES,
    )
    assert hint.observation == "idle 3h · last entry: assistant"
