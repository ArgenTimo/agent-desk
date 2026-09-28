"""What the board shows beside the sessions, one lane at a time (task 22).

The sessions themselves are `routes.board()`. Everything else on the board's left column — the
background jobs waiting on a human (B1), the open pull requests of the named repositories (B3) —
is a *lane*: a function that reads its own source and returns the template fields it fills and
the notices it has. A new lane is a function here and a block in `_board.html`; `routes.py`, which
renders the board in two places, does not change.

Blocking by contract, like `routes.board()`: the caller runs `read_lanes` in a thread.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent_desk.observe import jobs
from agent_desk.web import pulls


@dataclass(frozen=True)
class Lane:
    fields: dict[str, Any] = field(default_factory=dict)
    notices: list[str] = field(default_factory=list)


def _waiting_jobs() -> Lane:
    """Background jobs the CLI marked `blocked` — a fact, not an inference (B1)."""
    read = jobs.read_jobs()
    return Lane({"waiting_jobs": read.waiting, "waiting_questions": read.questions}, read.notices)


def _pull_requests() -> Lane:
    """Open pull requests of the repositories in AGENT_DESK_PULL_REPOS (B3)."""
    return Lane({"pull_lines": pulls.lines()})


LANES: list[Callable[[], Lane]] = [_waiting_jobs, _pull_requests]


def read_lanes() -> Lane:
    """Every lane, merged: their fields for the template, their notices in lane order."""
    fields: dict[str, Any] = {}
    notices: list[str] = []
    for lane in LANES:
        read = lane()
        fields.update(read.fields)
        notices.extend(read.notices)
    return Lane(fields, notices)
