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


@pytest.mark.unit
def test_a_question_with_a_list_under_it_becomes_buttons() -> None:
    """ "Когда в сессии предлагается выбрать решение — это отображается кнопками." A session that
    stopped on "1. keep it 2. rewrite it" is waiting on one word."""
    from agent_desk.observe.model import choices_in

    assert choices_in("Which one?\n1. keep it\n2. rewrite it\n3. leave it alone") == [
        "keep it",
        "rewrite it",
        "leave it alone",
    ]
    assert choices_in("What next?\n1) start over\n2) carry on") == ["start over", "carry on"]


@pytest.mark.unit
def test_everything_it_is_unsure_about_it_leaves_alone() -> None:
    """The failure mode is a button that sends the wrong thing, so it is narrow on purpose and the
    field beside the buttons is always there."""
    from agent_desk.observe.model import choices_in

    # No question: a numbered list in prose is not a choice.
    assert choices_in("I did three things.\n1. read it\n2. fixed it\n3. tested it") == []
    # One option is not a choice.
    assert choices_in("Shall I?\n1. yes") == []
    # A list that does not start at 1, or skips, is not read.
    assert choices_in("Which?\n2. this one\n3. that one") == []
    # A paragraph is not an option.
    assert choices_in("Which?\n1. " + "a very long line " * 8 + "\n2. no") == []
    # A year in prose is not a list.
    assert choices_in("Was it right?\nIn 1990. the parser changed") == []


@pytest.mark.unit
def test_only_the_last_word_from_the_session_offers_choices() -> None:
    """A question somebody already answered is not still open."""
    from agent_desk.observe.model import TailEntry, TranscriptTail

    asked = TranscriptTail(
        session_id="s",
        entries=[TailEntry(role="assistant", text="Which?\n1. keep it\n2. drop it")],
    )
    assert asked.choices == ["keep it", "drop it"]

    answered = TranscriptTail(
        session_id="s",
        entries=[
            TailEntry(role="assistant", text="Which?\n1. keep it\n2. drop it"),
            TailEntry(role="user", text="keep it"),
        ],
    )
    assert answered.choices == []


@pytest.mark.unit
def test_a_session_that_stopped_signing_has_lost_the_brief_with_it() -> None:
    """The canary works because the instruction to sign is in the *first* message: a window that
    has rolled far enough to lose the signature has lost the rest of the brief too."""
    from agent_desk.observe.model import lost_the_canary, signed_by

    # Generous about how it signs — what is being detected is that it stopped.
    for said in ("biba: done", "**biba**: done", "[biba] done", "biba — done", "  Biba: done"):
        assert signed_by(said, "biba"), said
        assert not lost_the_canary(said, "biba")

    assert lost_the_canary("I have finished the parser.", "biba")
    # Nobody else's session was told to sign anything, so an unsigned reply there means nothing.
    assert not lost_the_canary("I have finished the parser.", "")
    assert not lost_the_canary("   ", "biba")


@pytest.mark.unit
def test_a_lost_canary_leads_to_an_action_and_not_only_a_flag() -> None:
    """ "Потерянная канарейка должна вести к действию, а не только к флажку."

    The action is the half that costs nothing irreversible: a *new* session, with the brief, in the
    same project. Nothing is closed and nothing is thrown away — the old one keeps whatever it has
    not committed, and ending it stays a thing a person does in the terminal that has it
    (docs/adr/0002)."""
    markup = (
        Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "templates" / "_board.html"
    ).read_text(encoding="utf-8")
    at = markup.index("It has stopped signing as")
    around = markup[at : at + 1200]

    assert "start a fresh one" in around
    assert "/projects/instance?key=" in around


@pytest.mark.unit
def test_nothing_about_a_lost_canary_closes_anything() -> None:
    """Closing a session throws away whatever it has not committed, and that is not a call this
    console makes — by a loop or by a button somebody might press by mistake."""
    markup = (
        Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "templates" / "_board.html"
    ).read_text(encoding="utf-8")
    at = markup.index("It has stopped signing as")
    around = markup[at : at + 1200]

    for ending in ("/stop", "/close", "/end", "data-stop"):
        assert ending not in around, f"the canary line offers {ending!r}"


# --- and the session nobody can be asked in (docs/stories/04) --------------------------------------
@pytest.mark.unit
def test_a_background_agent_is_never_inferred_to_be_waiting_for_a_person() -> None:
    """Thirty-four of thirty-eight rows on a real board said "may want you". Every one of them was
    a `--bg` agent, and the single session a person was sitting in said nothing at all.

    The three conditions are sound and unchanged. What was wrong is where they were applied: a
    background agent has no prompt for anybody to wait at, and this console is the thing that made
    that true — `dispatch.build_task` writes "you cannot be asked anything once you start" into the
    brief of every one it starts.

    A guess applied where its premise is false is CLAUDE.md's fifth rule in its subtlest form: the
    flag always said "a guess, not a signal" and carried its observation, and no amount of hedging
    in the wording repairs a premise that is not true.
    """
    for kind in ("bg", "background"):
        hint = attention_hint(
            _session(status="idle", kind=kind, statusUpdatedAt=NOW - 14 * 60_000),
            _tail("assistant"),
            now=NOW,
            after_seconds=FIVE_MINUTES,
        )

        assert not hint.waiting, f"a {kind} session is flagged as possibly waiting for a person"
        assert hint.finished, "and it does not say what it did instead"
        assert hint.observation == "idle 14m · last entry: assistant", (
            "the observation the reading was made from went with the flag"
        )


@pytest.mark.unit
def test_a_session_somebody_is_sitting_in_is_still_flagged() -> None:
    """The whole point of narrowing it. A flag on nine rows in ten is not a flag; a flag on the one
    row where somebody may be needed is the thing the board is worth opening for."""
    hint = attention_hint(
        _session(status="idle", kind="interactive", statusUpdatedAt=NOW - 14 * 60_000),
        _tail("assistant"),
        now=NOW,
        after_seconds=FIVE_MINUTES,
    )

    assert hint.waiting
    assert not hint.finished


@pytest.mark.unit
def test_the_two_readings_are_never_both_true() -> None:
    """One of them is a reason to stop what you are doing and the other is not. A row that said
    both would be a row that answers the question twice."""
    for kind in ("bg", "background", "interactive", "shell", "something-new"):
        for status in ("idle", "busy", "shell"):
            for last in ("assistant", "user", None):
                for quiet in (0, 14):
                    hint = attention_hint(
                        _session(status=status, kind=kind, statusUpdatedAt=NOW - quiet * 60_000),
                        _tail(last),
                        now=NOW,
                        after_seconds=FIVE_MINUTES,
                    )

                    assert not (hint.waiting and hint.finished)


@pytest.mark.unit
def test_a_background_agent_that_has_finished_does_not_sort_above_the_work() -> None:
    """It used to. Thirty-four agents that had stopped ranked first, so the board opened with
    everything that needed nothing."""
    done = _session(status="idle", kind="bg", statusUpdatedAt=NOW - 14 * 60_000)
    hint = attention_hint(done, _tail("assistant"), now=NOW, after_seconds=FIVE_MINUTES)
    busy = _session(status="busy")

    assert triage_rank(done, hint) > triage_rank(
        busy, attention_hint(busy, _tail("assistant"), now=NOW, after_seconds=FIVE_MINUTES)
    )


@pytest.mark.unit
def test_a_background_agent_still_working_says_neither() -> None:
    """ "It has finished a turn" is a reading of silence. There is no silence here."""
    hint = attention_hint(
        _session(status="busy", kind="bg", statusUpdatedAt=NOW - 14 * 60_000),
        _tail("assistant"),
        now=NOW,
        after_seconds=FIVE_MINUTES,
    )

    assert not hint.waiting and not hint.finished
