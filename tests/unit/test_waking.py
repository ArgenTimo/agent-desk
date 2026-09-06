"""Reading a moment out of a sentence, and deciding whether it has come.

Both halves are pure, and both are tested against a fixed clock rather than the real one — a
deferral test that waits for tomorrow is a test nobody runs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from agent_desk.ideas import waking

NOW = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)  # a Wednesday afternoon


@pytest.mark.unit
def test_a_line_with_no_moment_in_it_is_not_a_deferral() -> None:
    """The ordinary case, and it has to be cheap: every idea captured goes through this.

    A thought that merely *mentions* time is not a deferral either — "the gate is slow" names no
    moment, and reading one out of it would put somebody's thought in a queue they never asked
    for.
    """
    assert waking.read("cache the probe results", now=NOW) is None
    assert waking.read("the gate is slow lately", now=NOW) is None
    assert waking.read("", now=NOW) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("напомни завтра про хинты", datetime(2026, 3, 5, 9, 0, tzinfo=UTC)),
        ("remind me tomorrow", datetime(2026, 3, 5, 9, 0, tzinfo=UTC)),
        ("вернись к этому через час", NOW + timedelta(hours=1)),
        ("come back to this in 2 hours", NOW + timedelta(hours=2)),
        ("look at it in 30 minutes", NOW + timedelta(minutes=30)),
        ("через 15 минут", NOW + timedelta(minutes=15)),
        ("next week, the folder cards", datetime(2026, 3, 11, 9, 0, tzinfo=UTC)),
    ],
)
def test_a_named_moment_is_a_clock(said: str, expected: datetime) -> None:
    """ "Напомни завтра" — nothing has to be true except that time has passed."""
    wake = waking.read(said, now=NOW)

    assert wake is not None
    assert wake.at == int(expected.timestamp())
    assert wake.when is None


@pytest.mark.unit
def test_tonight_said_after_dark_is_not_a_moment_that_has_gone() -> None:
    """Seven in the evening is what "tonight" means, until it is past seven.

    A moment in the past fires on the very next pass, which turns "напомни вечером" typed at
    nine into "напомни немедленно" — the one reading of it nobody means.
    """
    late = datetime(2026, 3, 4, 21, 0, tzinfo=UTC)
    wake = waking.read("вечером глянь на верстак", now=late)

    assert wake is not None
    assert wake.at is not None
    assert wake.at > int(late.timestamp())


@pytest.mark.unit
@pytest.mark.parametrize(
    ("said", "condition"),
    [
        ("когда освободится — доделай канарейку", "free"),
        ("как освободишься, посмотри логи", "free"),
        ("when nothing is running, run the sweep", "free"),
        ("когда лимиты отпустят, продолжай", "free"),
        ("после того как пройдёт гейт — мержим", "gate"),
        ("once the gate is green, land it", "gate"),
        ("when the gate passes, push it", "gate"),
    ],
)
def test_a_computed_moment_is_a_condition_with_a_name(said: str, condition: str) -> None:
    """ "Когда освободится", "после того как пройдёт гейт" — defined by the world, not the calendar."""
    wake = waking.read(said, now=NOW)

    assert wake is not None
    assert wake.when == condition
    assert wake.at is None


@pytest.mark.unit
def test_a_condition_this_program_cannot_check_is_refused_rather_than_stored() -> None:
    """The whole reason `wakes_when` holds a name and not free text.

    A condition nobody can evaluate is indistinguishable from a moment that never arrives, and a
    column that accepted any sentence would fill up with exactly those. Refusing at construction
    means the impossible row cannot be written at all.
    """
    with pytest.raises(ValueError, match="no such condition"):
        waking.Wake(when="when the client is happy")


@pytest.mark.unit
def test_a_moment_can_be_both_a_clock_and_a_condition() -> None:
    """ "Завтра, когда гейт позеленеет" is one moment with two halves, and it needs both."""
    wake = waking.read("завтра, когда пройдёт гейт", now=NOW)

    assert wake is not None
    assert wake.at is not None
    assert wake.when == "gate"

    # Tomorrow has come but the gate has not.
    tomorrow = NOW + timedelta(days=1)
    assert not waking.has_come(wake, now=tomorrow, anything_running=False, gate_is_green=False)
    assert waking.has_come(wake, now=tomorrow, anything_running=False, gate_is_green=True)
    # The gate is green but tomorrow has not come.
    assert not waking.has_come(wake, now=NOW, anything_running=False, gate_is_green=True)


@pytest.mark.unit
def test_a_clock_that_has_not_come_round_has_not_come_round() -> None:
    wake = waking.Wake(at=int((NOW + timedelta(hours=3)).timestamp()))

    assert not waking.has_come(wake, now=NOW, anything_running=False, gate_is_green=True)
    assert waking.has_come(
        wake, now=NOW + timedelta(hours=4), anything_running=True, gate_is_green=False
    )


@pytest.mark.unit
def test_when_free_waits_for_the_machine_to_be_free() -> None:
    """And nothing else: a machine with nothing running satisfies it whatever the gate says."""
    wake = waking.Wake(when="free")

    assert not waking.has_come(wake, now=NOW, anything_running=True, gate_is_green=True)
    assert waking.has_come(wake, now=NOW, anything_running=False, gate_is_green=False)


@pytest.mark.unit
def test_every_condition_in_the_vocabulary_is_one_something_can_answer() -> None:
    """The vocabulary and the check are edited together or this fails.

    `CONDITIONS` is what somebody's phrase is allowed to become, and `has_come` is what turns it
    into a yes or a no. A word in the first with no branch in the second is a deferral that never
    fires, filed under a name that reads like it works.
    """
    for condition in waking.CONDITIONS:
        wake = waking.Wake(when=condition)
        answers = {
            waking.has_come(wake, now=NOW, anything_running=running, gate_is_green=green)
            for running in (True, False)
            for green in (True, False)
        }
        assert answers == {True, False}, (
            f"the condition {condition!r} is in the vocabulary but `has_come` does not branch on "
            "it — it either always fires or never does"
        )


@pytest.mark.unit
def test_what_a_card_says_about_when_it_comes_back() -> None:
    """A deferral nobody can read is the thing this replaced."""
    assert "when nothing is running" in waking.Wake(when="free").says
    both = waking.Wake(at=int(NOW.timestamp()), when="gate").says
    assert "once the gate is green" in both
    assert "14:30" in both, "the clock half is missing, so the card promises a time it has not got"
