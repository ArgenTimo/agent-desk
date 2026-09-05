"""What a subscription's header may claim, and the number it must not invent.

The idea asked for "сколько осталось процентов до утыкания в лимит". There is no such number on
this machine, so most of these assert what the card does *not* say.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from agent_desk.store.repo import Kicking, Store, Subscription
from agent_desk.web import plans

NOW = 1_788_400_000_000


@dataclass
class _Session:
    session_id: str
    project: str


@dataclass
class _Tail:
    context_tokens: int | None


@dataclass
class _Row:
    session: _Session
    tail: _Tail


def _row(short: str, project: str, tokens: int | None) -> _Row:
    return _Row(_Session(f"{short}-1111-4222-8333-444444444444", project), _Tail(tokens))


def _plan(name: str = "Claude Max", limit: int | None = None) -> Subscription:
    return Subscription(id="p1", name=name, service="claude code", limit_tokens=limit, created_at=0)


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


@pytest.mark.unit
def test_a_plan_adds_up_what_this_console_has_seen() -> None:
    """Observed, not billed: the context each session is carrying, which the board already reads."""
    made = plans.plans(
        [_plan(limit=100_000)],
        [_row("aaa", "agent-desk", 30_000), _row("bbb", "other", 20_000)],
        {"aaa": "p1", "bbb": "p1"},
        {},
        NOW,
    )

    (one,) = made
    assert one.sessions == 2
    assert one.seen_tokens == 50_000
    assert one.percent == 50
    # It spans projects, which is what makes it the block above them.
    assert one.projects == ["agent-desk", "other"]


@pytest.mark.unit
def test_without_a_stated_limit_there_is_no_percentage_to_show() -> None:
    """A percentage presented as an account balance would be the guessed status CLAUDE.md's fifth
    rule is about, wearing a progress bar."""
    (one,) = plans.plans([_plan()], [_row("aaa", "agent-desk", 30_000)], {"aaa": "p1"}, {}, NOW)

    assert one.seen_tokens == 30_000
    assert one.percent is None
    assert not one.close


@pytest.mark.unit
def test_a_plan_that_is_out_says_when_it_comes_back() -> None:
    """The one hard fact available: a `--resume` the CLI refused for want of budget."""
    kicked = Kicking(short_id="aaa", armed_at=1, resume_at=NOW + 900_000)

    (one,) = plans.plans(
        [_plan(limit=100)], [_row("aaa", "agent-desk", 10)], {"aaa": "p1"}, {"aaa": kicked}, NOW
    )

    assert one.out
    assert one.out_until == NOW + 900_000


@pytest.mark.unit
def test_a_break_that_is_over_is_not_a_break() -> None:
    kicked = Kicking(short_id="aaa", armed_at=1, resume_at=NOW - 60_000)

    (one,) = plans.plans(
        [_plan()], [_row("aaa", "agent-desk", 10)], {"aaa": "p1"}, {"aaa": kicked}, NOW
    )

    assert not one.out


@pytest.mark.unit
def test_a_session_on_no_plan_is_counted_against_none() -> None:
    (one,) = plans.plans([_plan(limit=100)], [_row("aaa", "agent-desk", 90)], {}, {}, NOW)

    assert one.sessions == 0
    assert one.seen_tokens == 0


@pytest.mark.unit
def test_the_percentage_never_runs_past_the_end_of_the_bar() -> None:
    (one,) = plans.plans([_plan(limit=100)], [_row("aaa", "a", 400)], {"aaa": "p1"}, {}, NOW)

    assert one.percent == 100
    assert one.close


@pytest.mark.unit
async def test_a_move_can_be_temporary_and_undoes_itself(desk: Store) -> None:
    """ "Временно" has to mean something if nobody is going to remember to move it back."""
    from agent_desk.store.repo import _now_ms

    first = await desk.add_subscription(name="Max", limit_tokens=1000)
    second = await desk.add_subscription(name="Team")
    assert first is not None and second is not None

    await desk.move_session("aaa", first.id)
    assert await desk.session_subscriptions() == {"aaa": first.id}

    # Moved for a while, then it goes back on its own.
    await desk.move_session("aaa", second.id, until=_now_ms() + 3_600_000)
    assert await desk.session_subscriptions() == {"aaa": second.id}

    await desk.move_session("aaa", second.id, until=_now_ms() - 1)
    assert await desk.session_subscriptions() == {}

    # And taken off outright.
    await desk.move_session("aaa", first.id)
    await desk.move_session("aaa", "")
    assert await desk.session_subscriptions() == {}


@pytest.mark.unit
async def test_forgetting_a_plan_takes_its_sessions_off_it(desk: Store) -> None:
    plan = await desk.add_subscription(name="Max")
    assert plan is not None
    await desk.move_session("aaa", plan.id)

    await desk.drop_subscription(plan.id)

    assert await desk.subscriptions() == []
    assert await desk.session_subscriptions() == {}


@pytest.mark.unit
async def test_a_plan_with_no_name_is_not_a_plan(desk: Store) -> None:
    assert await desk.add_subscription(name="   ") is None
    assert await desk.subscriptions() == []
