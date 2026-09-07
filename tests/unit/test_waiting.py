"""The suite waits for facts, not for lengths of time (01M1XED1EC79…).

"Наблюдение с этой недели: полный прогон падал восемью тестами, пока рядом работала живая консоль,
и проходил начисто, когда её останавливали… Тест, падающий от погоды, — это тест, который люди
учатся игнорировать, а вместе с ним начинают игнорировать красный прогон вообще."

The second sentence is why this is worth a rule of its own. A gate people have learned to ignore is
worse than no gate: it still costs the time, and it no longer buys the confidence.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from tests.unit.waiting import until

TESTS = pathlib.Path(__file__).resolve().parent

# A guess about how fast the machine is. Two spellings are not that and are allowed:
#
#   `sleep(0)`  yields to the loop — a statement about ordering rather than about time;
#   `sleep(30)` inside a stub is a thing that never returns, which is how a test makes a loop hang
#               so it can check that cancelling it works.
#
# Five seconds is the line between them, and it is a wide gap: nothing in this suite legitimately
# waits four seconds, and nothing that means "never" says less than thirty.
_A_DURATION = re.compile(r"asyncio\.sleep\(\s*([0-9.]+)\s*\)")
FOREVER = 5.0


def _guesses(line: str) -> bool:
    found = _A_DURATION.search(line)
    return bool(found) and 0 < float(found.group(1)) < FOREVER


# This file is not scanned: it has to contain the shapes it forbids, in the pattern above and in
# the test that proves the pattern catches them.
def _files() -> list[pathlib.Path]:
    return sorted(p for p in TESTS.glob("test_*.py") if p.name != "test_waiting.py")


def _code(where: pathlib.Path) -> str:
    """The file with its comments and docstrings' prose left out.

    A rule against writing `asyncio.sleep(0.3)` trips over the paragraph explaining the rule —
    which is how this file's first draft failed on `waiting.py`'s own docstring.
    """
    lines = []
    for line in where.read_text(encoding="utf-8").splitlines():
        bare = line.lstrip()
        if bare.startswith("#") or bare.startswith('"') or bare.startswith("`"):
            continue
        lines.append(line)
    return "\n".join(lines)


@pytest.mark.unit
def test_no_test_waits_for_a_length_of_time() -> None:
    """Every wait in this suite is waiting for a fact — a block has settled, a loop has come round,
    a process has been reaped. Written as a duration, the number is a guess about how fast the
    machine is, and this project is normally worked on with several agents and a live console on
    the same laptop: the guess is wrong exactly when the suite matters most."""
    guessing = [
        f"{where.name}:{n}"
        for where in _files()
        for n, line in enumerate(_code(where).splitlines(), start=1)
        if _guesses(line)
    ]

    assert not guessing, (
        "these wait for a length of time rather than for the thing they are waiting for; "
        f"tests/unit/waiting.py is how to say it instead: {guessing}"
    )


@pytest.mark.unit
def test_the_check_can_actually_fail() -> None:
    """A rule enforced by a search is worth proving catches something, and worth proving it lets
    the two legitimate spellings through."""
    assert _guesses("    await asyncio.sleep(0.3)")
    assert _guesses("await asyncio.sleep(1)")
    assert not _guesses("await asyncio.sleep(0)"), "yielding to the loop is not waiting"
    assert not _guesses("await asyncio.sleep(30)"), "a stub that never returns is not waiting"


@pytest.mark.unit
async def test_waiting_returns_as_soon_as_the_thing_is_true() -> None:
    """The whole reason this is not slower than the sleeps it replaces."""
    seen = [0]

    async def third_time() -> bool:
        seen[0] += 1
        return seen[0] == 3

    await until(third_time, "the third look")

    assert seen[0] == 3


@pytest.mark.unit
async def test_waiting_says_what_it_was_waiting_for() -> None:
    """Failing here rather than three lines later, on an assertion about something that had not
    happened yet, is most of the value: the old loops gave up and let the test carry on."""
    with pytest.raises(AssertionError, match="both questions are running"):
        await until(lambda: False, "both questions are running", seconds=0.05)


@pytest.mark.unit
async def test_a_predicate_that_is_not_a_question_is_refused() -> None:
    """A truthy value is not an answer to "is this true yet". The commonest way to write one by
    mistake is an async predicate that was never awaited, which this cannot catch — a coroutine
    compared to a value really is a `bool`, and a true one — so `until` says so in its own words
    instead. What it can catch is a predicate that answers with something that is not a question's
    answer at all, and refusing that where it was written beats waiting twenty seconds for it."""

    with pytest.raises(TypeError, match="bool"):
        await until(lambda: len([1, 2]), "two of something", seconds=0.05)  # type: ignore[arg-type]
