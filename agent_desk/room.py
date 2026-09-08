"""How much work this machine could actually start right now, and why that is the number.

"Поднимается объективное количество инстансов, сессий, агентов… Сколько работы можно вести
параллельно — это функция от того, на сколько независимых кусков разбивается задача, и от правил,
которые уже есть: один агент на проект, бюджет в час, два падения подряд выключают. Число должно
вычисляться и объясняться, а не задаваться."

The rules were all there and none of them was ever added up. Each project knew, one at a time, why
it could not start anything — `autostart.why_not` — and nobody could see the answer to "how much
could be going on here at once", which is the question somebody asks before deciding to queue five
more things.

## Every number here has a reason attached to it

That is the whole design. A count on its own is a number to argue with; a count that says "three:
one here, two there, and this one is disarmed after two failures" is a count somebody can act on.
So a project never contributes a bare integer — it contributes a seat and the sentence for it, and
the total is the seats, not the other way round.

## What it does not claim

It counts the work that is *queued*. Nothing in this program splits one piece of work into several
independent ones, so "on how many independent pieces the task divides" is, today, "how many tasks
somebody or some board queued" — and that is said in words rather than passed off as a measure of
parallelism this console does not have.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Seat:
    """One project's answer: whether it could start something, and why not when it could not."""

    repo_key: str
    name: str
    free: bool
    why: str
    waiting: int

    @property
    def says(self) -> str:
        if self.free:
            more = "" if self.waiting == 1 else "s"
            return f"{self.name} could start one now — {self.waiting} thing{more} queued"
        return f"{self.name} could not: {self.why}"


@dataclass(frozen=True)
class Room:
    seats: tuple[Seat, ...]

    @property
    def at_once(self) -> int:
        """How many agents could be started this minute. One per free seat, because one per
        project is the rule and this only adds it up."""
        return sum(1 for seat in self.seats if seat.free)

    @property
    def said(self) -> str:
        """The number, in a sentence, for the one line a console has room for."""
        if not self.seats:
            return "nothing here to start work in"
        if not self.at_once:
            return "nothing could start right now"
        return f"{self.at_once} could start now, of {len(self.seats)}"

    @property
    def lines(self) -> list[str]:
        """The reason for every project, free or not. In the order they were given, so the console
        and this agree about which project is which."""
        return [seat.says for seat in self.seats]


def how_many(seats: Sequence[Seat]) -> Room:
    """Add the seats up. Pure, and deliberately trivial: everything that could be wrong here is in
    what the caller read, and a function that recomputed the rules would be a second copy of
    `autostart.why_not` disagreeing with it on a Tuesday."""
    return Room(seats=tuple(seats))
