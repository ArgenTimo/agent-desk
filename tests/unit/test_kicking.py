"""A session that is not allowed to idle, and the six times it is left alone (docs/adr/0009).

This module argues with the oldest rule in the repository, so almost every test here asserts that
nothing was sent. That is the shape of the thing: one narrow permission and six reasons to refuse,
and the reasons are what somebody has to trust at three in the morning.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import pathlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from agent_desk import dispatch
from agent_desk.observe.model import Session
from agent_desk.store.repo import Store
from agent_desk.web import kicking

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
SHORT = "abc12345"
FULL = "abc12345-1111-4222-8333-444444444444"
NOW = 1_788_400_000_000


def _session(**overrides: Any) -> Session:
    entry: dict[str, Any] = json.loads((FIXTURES / "registry_entry.json").read_text())
    entry.update({"sessionId": FULL, "kind": "bg", "status": "idle", **overrides})
    return Session.model_validate(entry)


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """A kick that always works, and the list of what was actually sent."""
    asked: list[tuple[str, str]] = []

    def fake_kick(
        session_id: str, instruction: str, *, cwd: str, agent_id: str = ""
    ) -> dispatch.Started:
        asked.append((session_id, instruction))
        return dispatch.Started(True, agent_id=agent_id or session_id.split("-")[0])

    monkeypatch.setattr(dispatch, "kick", fake_kick)
    return asked


@pytest.fixture
def one_idle_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kicking, "_sessions", lambda: {SHORT: _session()})


@pytest.mark.unit
async def test_an_idle_background_session_that_was_switched_on_is_continued(
    desk: Store, sent: list[tuple[str, str]], one_idle_session: None
) -> None:
    await desk.kick_session(SHORT, on=True, session_id=FULL, cwd="/somewhere")

    assert await kicking.tick(desk) == SHORT

    session_id, instruction = sent[0]
    assert session_id == FULL
    # Every kicked turn says who sent it: a transcript read in a month has to show which turns a
    # person asked for (docs/adr/0009).
    assert "sent by agent-desk, not by a person" in instruction
    assert (await desk.kicking(SHORT)).kicks == 1


@pytest.mark.unit
async def test_a_session_nobody_switched_on_is_never_touched(
    desk: Store, sent: list[tuple[str, str]], one_idle_session: None
) -> None:
    """The default, and the state every session on the board is in."""
    assert await kicking.tick(desk) == ""
    assert sent == []


@pytest.mark.unit
async def test_a_session_that_is_working_is_never_interrupted(
    desk: Store, sent: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/adr/0002's surviving half, and the one clause of it 0009 does not touch."""
    monkeypatch.setattr(kicking, "_sessions", lambda: {SHORT: _session(status="busy")})
    await desk.kick_session(SHORT, on=True, session_id=FULL, cwd="/somewhere")

    assert await kicking.tick(desk) == ""
    assert sent == []


@pytest.mark.unit
async def test_a_session_in_a_terminal_is_left_alone_and_says_why(
    desk: Store, sent: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`stop` and `--resume` are the CLI's door into a background session. A terminal has none
    this program is allowed to open — the other one needs a credential (CLAUDE.md, rule three)."""
    monkeypatch.setattr(kicking, "_sessions", lambda: {SHORT: _session(kind="interactive")})
    await desk.kick_session(SHORT, on=True, session_id=FULL, cwd="/somewhere")

    assert await kicking.tick(desk) == ""
    assert sent == []
    assert "only a background session" in kicking.kickable(_session(kind="interactive"))


@pytest.mark.unit
async def test_the_hour_s_budget_stops_a_burst(
    desk: Store, sent: list[tuple[str, str]], one_idle_session: None
) -> None:
    await desk.kick_session(SHORT, on=True, session_id=FULL, cwd="/somewhere", per_hour=2)

    assert await kicking.tick(desk) == SHORT
    assert await kicking.tick(desk) == SHORT
    assert await kicking.tick(desk) == ""
    assert len(sent) == 2
    arming = await desk.kicking(SHORT)
    assert "budget is spent (2 of 2)" in kicking.why_not_kick(arming, _session(), NOW, 2)


@pytest.mark.unit
async def test_a_limit_is_a_wait_and_the_switch_stays_on(
    desk: Store, one_idle_session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is broken; there is simply nothing to spend. Switching off here would mean the
    console never came back after lunch."""
    monkeypatch.setattr(
        dispatch,
        "kick",
        lambda *a, **k: dispatch.Started(False, detail="usage limit reached · resets at 14:00"),
    )
    await desk.kick_session(SHORT, on=True, session_id=FULL, cwd="/somewhere")

    assert await kicking.tick(desk) == ""

    arming = await desk.kicking(SHORT)
    assert arming.armed, "a limit must never switch it off"
    assert arming.failures == 0, "a limit is not a failure and must not count towards two"
    assert arming.resume_at is not None and arming.waiting(NOW) is (arming.resume_at > NOW)
    assert "out of budget" in kicking.why_not_kick(arming, _session(), arming.resume_at - 1, 0)
    # And once the wait is over it goes again, without anybody pressing anything.
    assert kicking.why_not_kick(arming, _session(), arming.resume_at + 1, 0) == ""


@pytest.mark.unit
async def test_two_failures_in_a_row_switch_it_off_and_say_why(
    desk: Store, one_idle_session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rule that keeps firing into a broken condition is the three-in-the-morning failure."""
    monkeypatch.setattr(
        dispatch, "kick", lambda *a, **k: dispatch.Started(False, detail="it would not resume")
    )
    await desk.kick_session(SHORT, on=True, session_id=FULL, cwd="/somewhere")

    await kicking.tick(desk)
    assert (await desk.kicking(SHORT)).armed
    await kicking.tick(desk)

    arming = await desk.kicking(SHORT)
    assert not arming.armed
    assert arming.disarmed_why is not None and "it would not resume" in arming.disarmed_why


@pytest.mark.unit
async def test_a_session_that_has_gone_is_not_an_error(
    desk: Store, sent: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """It has nothing left to continue, and saying so beats guessing that it is idle."""
    monkeypatch.setattr(kicking, "_sessions", dict)
    await desk.kick_session(SHORT, on=True, session_id=FULL, cwd="/somewhere")

    assert await kicking.tick(desk) == ""
    assert sent == []
    assert (await desk.kicking(SHORT)).armed, "gone is not a failure and does not disarm it"
    assert "not running any more" in kicking.why_not_kick(await desk.kicking(SHORT), None, NOW, 0)


@pytest.mark.unit
async def test_a_console_with_nothing_switched_on_reads_no_registry(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary case, and it has to cost nothing: no registry read, no thread."""

    def never() -> dict[str, Session]:  # pragma: no cover — reaching it is the failure
        raise AssertionError("the registry was read with nothing switched on")

    monkeypatch.setattr(kicking, "_sessions", never)
    assert await kicking.tick(desk) == ""


@pytest.mark.unit
def test_the_prompt_never_invents_the_work() -> None:
    """Two prompts and there is no third: carry on, or the fence docs/adr/0008 already wrote."""
    from agent_desk.store.repo import Kicking

    said = kicking.carry_on(Kicking(short_id=SHORT), _session())

    assert "is not finished, continue it" in said
    # The exploring instruction, reused rather than rebuilt, with its own refusals inside it.
    assert "find one thing worth fixing" in said or "one thing" in said
    assert "add a feature" in said


@pytest.mark.unit
async def test_only_one_session_is_continued_in_a_tick(
    desk: Store, sent: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing here is urgent, and a burst is the thing this file exists not to do."""
    other = "def67890"
    monkeypatch.setattr(
        kicking,
        "_sessions",
        lambda: {
            SHORT: _session(),
            other: _session(sessionId=f"{other}-1111-4222-8333-444444444444"),
        },
    )
    await desk.kick_session(SHORT, on=True, session_id=FULL, cwd="/somewhere")
    await desk.kick_session(other, on=True, session_id=f"{other}-x", cwd="/somewhere")

    await kicking.tick(desk)

    assert len(sent) == 1


@pytest.mark.unit
async def test_both_loops_stop_when_the_cancel_lands_inside_a_pass(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`app.lifespan` cancels these and then waits for them, so they have to end.

    The cancel arriving while a loop is parked between passes was always fine. The one that
    matters is the other one: a pass sits in a thread for as long as `dispatch.kick` takes to
    start a session, or for as long as several model calls take to read the pool — and a
    cancellation swallowed there leaves the TaskGroup waiting for a task that never finishes.

    An exploration found exactly this in `autostart.run`. These two had the same shape.
    """

    async def one_loop(loop: object, patch: object) -> None:
        inside = asyncio.Event()

        async def slow(*args: object, **kwargs: object) -> None:
            inside.set()
            await asyncio.sleep(30)

        patch(slow)  # type: ignore[operator]
        running = asyncio.create_task(loop(desk))  # type: ignore[operator]
        await inside.wait()
        running.cancel()

        _, pending = await asyncio.wait({running}, timeout=1)
        for task in pending:  # pragma: no cover — reaching this is the failure
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        assert not pending, "a loop swallowed the cancellation and went on running"

    await one_loop(kicking.run, lambda fake: monkeypatch.setattr(kicking, "tick", fake))
    await one_loop(
        kicking.appraising, lambda fake: monkeypatch.setattr(kicking.appraise, "sweep", fake)
    )


@pytest.mark.unit
async def test_a_pass_that_raises_does_not_end_the_loop(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A loop that took the console down with it would be a worse failure than anything it was
    started to do."""
    twice = asyncio.Event()
    calls: list[int] = []

    async def explodes(store: Store) -> None:
        calls.append(1)
        if len(calls) >= 2:
            twice.set()
        raise RuntimeError("something went wrong in a pass")

    monkeypatch.setattr(kicking, "tick", explodes)
    monkeypatch.setattr(kicking, "TICK_SECONDS", 0.01)

    running = asyncio.create_task(kicking.run(desk))
    try:
        async with asyncio.timeout(5):
            await twice.wait()
    finally:
        running.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await running

    assert len(calls) >= 2
