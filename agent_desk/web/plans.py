"""What a subscription's header can honestly say (025-subscriptions.sql).

The idea asked for "сколько осталось процентов до утыкания в лимит". There is no such number on
this machine: an account's remaining quota is not on disk, and nothing here has an API to ask for
it. A percentage presented as a balance would be the guessed status CLAUDE.md's fifth rule is
about, wearing a progress bar.

So this module computes the two things that *are* known, and the card says which is which:

- **what this console has seen** — the context each session on this plan is carrying, added up.
  Read from the transcripts the board already reads, so it costs nothing extra. It is not a bill
  and it is not everything ever spent; it is how much is in the air right now.
- **whether it is out** — a fact, not a reading: a `--resume` was refused for want of budget and
  the CLI said when to come back (docs/adr/0009).

The percentage exists only when somebody typed a limit in, and it is a percentage *of the number
they typed*, which the card also shows. Without one the card shows the observed number and no bar,
which is honest and still the most useful thing on the page when two plans are running.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from agent_desk.store.repo import Kicking, Subscription

# Where the bar changes colour. Amber is "look at this eventually" everywhere else on this page and
# it means the same here; red is kept for a plan that is actually out, which is a fact rather than
# a projection.
GETTING_CLOSE = 80


@dataclass(frozen=True)
class Plan:
    """One subscription, with what is on it and what is known about it."""

    subscription: Subscription
    sessions: int = 0
    # The context every session on this plan is carrying, added up. Observed, not billed.
    seen_tokens: int = 0
    # When a kick was refused for want of budget, the moment the CLI said to come back.
    out_until: int | None = None
    projects: list[str] = field(default_factory=list)

    @property
    def percent(self) -> int | None:
        """How much of the stated limit the observed number is, or `None` when none was stated."""
        limit = self.subscription.limit_tokens
        if not limit:
            return None
        return min(100, round(self.seen_tokens * 100 / limit))

    @property
    def close(self) -> bool:
        percent = self.percent
        return percent is not None and percent >= GETTING_CLOSE

    @property
    def out(self) -> bool:
        return self.out_until is not None


def plans(
    subscriptions: Sequence[Subscription],
    rows: Sequence[object],
    placed: dict[str, str],
    kicks: dict[str, Kicking],
    now_ms: int,
) -> list[Plan]:
    """Assemble every plan's card from what the board already read.

    `rows` are the board's rows — passed as objects rather than imported, because this module has
    no business knowing how a board row is put together, only that it has a session and a tail.
    """
    counted: dict[str, Plan] = {
        one.id: Plan(subscription=one, projects=[]) for one in subscriptions
    }
    sessions: dict[str, list[object]] = {one.id: [] for one in subscriptions}

    for row in rows:
        session = getattr(row, "session", None)
        if session is None:
            continue
        short = session.session_id.split("-")[0]
        on = placed.get(short)
        if on in sessions:
            sessions[on].append(row)

    for plan_id, on_it in sessions.items():
        seen = 0
        projects: list[str] = []
        out_until: int | None = None
        for row in on_it:
            tail = getattr(row, "tail", None)
            seen += getattr(tail, "context_tokens", None) or 0
            project = getattr(row.session, "project", "")  # type: ignore[attr-defined]
            if project and project not in projects:
                projects.append(project)
        for short, arming in kicks.items():
            if placed.get(short) == plan_id and arming.resume_at and arming.resume_at > now_ms:
                out_until = max(out_until or 0, arming.resume_at)
        counted[plan_id] = Plan(
            subscription=counted[plan_id].subscription,
            sessions=len(on_it),
            seen_tokens=seen,
            out_until=out_until,
            projects=projects,
        )
    return list(counted.values())
