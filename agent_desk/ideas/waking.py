"""When a deferred thing comes back.

*"Отложенная задача должна иметь момент срабатывания: либо вычисленный («когда освободится»,
«после того как пройдёт гейт»), либо названный («напомни завтра») — и в этот момент срабатывать
сама."*

A deferred task with no moment is a task nobody started, and that is what deferring was here
before this module: a thought filed among other thoughts, distinguishable from an abandoned one
only by whoever remembered writing it.

Two kinds of moment, and they are not the same thing.

**A named one** is a clock. "Завтра", "in two hours", "в понедельник" — nothing has to be true
except that time has passed, and the answer is an epoch second computed once, when it is said.

**A computed one** is a condition. "Когда освободится", "после того как пройдёт гейт" — the moment
is defined by the world rather than by the calendar, and it may be five minutes away or never. The
condition is stored as a *name from the list below* and never as free text, because a condition
nobody can evaluate is indistinguishable from a moment that never arrives, and free text produces
exactly those.

Everything here is pure. Reading a phrase, and deciding whether a moment has come, are both
functions of their arguments — the clock is passed in, the state of the world is passed in. What
actually goes and looks is `agent_desk/web/later.py`, which is where it can be seen doing it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# The conditions this program can actually check. Adding one means adding the check in
# `has_come` and the fact that feeds it in `agent_desk/web/later.py` — in that order, so that a
# condition never exists in the vocabulary before something can answer it.
#
# `free` is the one that matters most: it is what "когда освободится" means on this machine, and
# it is also what a limit lifting looks like from the outside.
CONDITIONS = {
    "free": "when nothing is running",
    "gate": "once the gate is green",
}

# A duration somebody said, and the phrases for it in both languages this console is used in.
_HOURS = re.compile(
    r"\b(?:in|через)\s+(?:(\d+)\s*)?(hour|hours|час|часа|часов|minute|minutes|минуту|минут|минуты)\b",
    re.IGNORECASE,
)
_MINUTE_WORDS = ("minute", "minutes", "минуту", "минут", "минуты")

# A day somebody named. Not a date parser: three words, which are the three that get said.
_TOMORROW = re.compile(r"\b(tomorrow|завтра)\b", re.IGNORECASE)
_TONIGHT = re.compile(r"\b(tonight|вечером|сегодня\s+вечером)\b", re.IGNORECASE)
_NEXT_WEEK = re.compile(r"\b(next\s+week|на\s+следующей\s+неделе|через\s+неделю)\b", re.IGNORECASE)

# And the conditions, said the way they are said.
_WHEN_FREE = re.compile(
    r"(когда\s+освобод\w*|как\s+освобод\w*|when\s+(?:it|you)?\s*(?:is|are)?\s*free"
    r"|when\s+nothing\s+is\s+running|когда\s+будет\s+свободн\w*|когда\s+лимит\w*\s+"
    r"(?:отпуст\w*|снимут\w*|сброс\w*))",
    re.IGNORECASE,
)
_WHEN_GREEN = re.compile(
    r"(после\s+того\s+как\s+пройд\w*\s+гейт|когда\s+пройд\w*\s+гейт|когда\s+гейт\s+"
    r"(?:позелен\w*|станет\s+зелён\w*|будет\s+зелён\w*)|after\s+the\s+gate|once\s+the\s+gate"
    r"|when\s+the\s+gate\s+(?:is\s+green|passes))",
    re.IGNORECASE,
)

# When "tomorrow" is, in hours past midnight. Not 00:00, which is a moment nobody means by it.
MORNING = 9
EVENING = 19


@dataclass(frozen=True)
class Wake:
    """The moment a deferred thing comes back, in whichever of the two ways it was said.

    Both halves may be present — "завтра, когда гейт позеленеет" is one moment, and it has come
    when both are true. Neither present is not a `Wake` at all; `read` returns `None`.
    """

    at: int | None = None
    when: str | None = None

    def __post_init__(self) -> None:
        if self.when is not None and self.when not in CONDITIONS:
            raise ValueError(f"no such condition: {self.when!r}")

    @property
    def says(self) -> str:
        """What to show on a card. The words somebody would have used."""
        parts = []
        if self.at is not None:
            parts.append(datetime.fromtimestamp(self.at, UTC).strftime("%a %d %b, %H:%M"))
        if self.when is not None:
            parts.append(CONDITIONS[self.when])
        return " · ".join(parts)


def read(text: str, *, now: datetime) -> Wake | None:
    """The moment a line asks for, or `None` when it asks for no moment at all.

    Pure, and the clock is an argument: a function that reads its own wall clock cannot be tested
    against tomorrow morning without waiting for it.
    """
    at = _clock(text, now=now)
    when = _condition(text)
    if at is None and when is None:
        return None
    return Wake(at=at, when=when)


def _condition(text: str) -> str | None:
    if _WHEN_GREEN.search(text):
        return "gate"
    if _WHEN_FREE.search(text):
        return "free"
    return None


def _clock(text: str, *, now: datetime) -> int | None:
    match = _HOURS.search(text)
    if match is not None:
        count = int(match.group(1) or 1)
        unit = match.group(2).lower()
        step = timedelta(minutes=count) if unit in _MINUTE_WORDS else timedelta(hours=count)
        return int((now + step).timestamp())
    if _NEXT_WEEK.search(text):
        return int(_at(now + timedelta(days=7), MORNING).timestamp())
    if _TOMORROW.search(text):
        return int(_at(now + timedelta(days=1), MORNING).timestamp())
    if _TONIGHT.search(text):
        evening = _at(now, EVENING)
        # "Tonight" said after seven means tonight, not a moment that has already gone.
        return int((evening if evening > now else now + timedelta(hours=1)).timestamp())
    return None


def _at(day: datetime, hour: int) -> datetime:
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


def has_come(wake: Wake, *, now: datetime, anything_running: bool, gate_is_green: bool) -> bool:
    """Whether this moment has arrived.

    Both halves must be true when both are set. The world is passed in rather than looked at, for
    the same reason the clock is: this is the decision, and it is checkable on its own.

    A condition nobody could answer is not reachable from here — `Wake` refuses to hold one — so
    there is no branch for it, and the day one is added the vocabulary and this function are edited
    together or `CONDITIONS` fails its own test.
    """
    if wake.at is not None and now.timestamp() < wake.at:
        return False
    if wake.when == "free" and anything_running:
        return False
    if wake.when == "gate" and not gate_is_green:
        return False
    return True
