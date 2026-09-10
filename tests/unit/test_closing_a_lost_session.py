"""Closing a session whose canary is lost (01M23GZE58QPF6F7VYDW3FCQ5M).

«Закрытие сессии выбрасывает то, что она не закоммитила. Это единственное необратимое действие во
всей консоли, и решение о нём должно приниматься с открытыми глазами, а не заодно с кнопкой.»

Three things, and none of them optional: a switch per project, a reading of the checkout first, and
an order that lets the session finish and commit before anything happens to it.
"""

from __future__ import annotations

import itertools
import pathlib
import urllib.parse
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest
from agent_desk import land, tidying
from agent_desk.observe.model import Session, now_ms
from agent_desk.store.repo import Store
from agent_desk.web import autostart, routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
LONG_ENOUGH = tidying.QUIET_FOR_MS + 60_000


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _a_form(fields: dict[str, str]) -> object:
    body = urllib.parse.urlencode(fields).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {
            "content-type": "application/x-www-form-urlencoded",
            "hx-request": "true",
        }

    return Filled()


def _may(**over: object) -> tidying.Maybe:
    fields: dict[str, Any] = {
        "armed": True,
        "canary_lost": True,
        "status": "idle",
        "clean": True,
        "idle_for_ms": LONG_ENOUGH,
    }
    return tidying.may_close(**{**fields, **over})


# --- the decision, and what it says when the answer is no ------------------------------------------
def test_all_four_and_it_may_close() -> None:
    assert _may().yes


def test_a_project_nobody_switched_on_closes_nothing() -> None:
    """Like everything that acts unattended (docs/adr/0008), and off."""
    said = _may(armed=False)

    assert not said.yes
    assert "not been switched on" in said.why


def test_a_session_still_signing_is_not_tidied() -> None:
    assert not _may(canary_lost=False).yes


@pytest.mark.parametrize("status", ["busy", "shell"])
def test_something_in_flight_is_not_something_to_close(status: str) -> None:
    """«Сначала дать доработать и закоммитить, только потом закрывать.»"""
    said = _may(status=status)

    assert not said.yes
    assert status in said.why


def test_uncommitted_work_stops_it() -> None:
    """The reading is the whole safety argument, and a closure that skipped it once would be the
    one that lost work."""
    said = _may(clean=False)

    assert not said.yes
    assert "uncommitted" in said.why


def test_a_session_that_went_quiet_a_minute_ago_waits() -> None:
    """The status field cannot tell "finished" from "between two turns of the same thing", so the
    wait is real time."""
    said = _may(idle_for_ms=60_000)

    assert not said.yes
    assert "more minute" in said.why


def test_the_answer_says_which_condition_failed() -> None:
    """A caller told "no" and not why has to go and work it out, and the place it would go is a
    session it was about to close."""
    for said in (_may(armed=False), _may(clean=False), _may(status="busy")):
        assert said.why


# --- the reading -----------------------------------------------------------------------------------
def test_a_checkout_that_cannot_be_read_counts_as_not_clean(tmp_path: pathlib.Path) -> None:
    """Not knowing is a reason not to close something."""
    clean, why = land.nothing_uncommitted(str(tmp_path / "nowhere"))

    assert not clean
    assert why


def test_a_clean_checkout_reads_as_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(land, "_git", lambda cwd, *args, **rest: (0, ""))

    assert land.nothing_uncommitted("/tmp/anywhere") == (True, "its checkout is clean")


def test_somebody_s_own_uncommitted_work_reads_as_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(land, "_git", lambda cwd, *args, **rest: (0, " M agent_desk/x.py"))

    clean, why = land.nothing_uncommitted("/tmp/anywhere")

    assert not clean and "uncommitted" in why


def test_the_cli_s_own_worktrees_are_not_somebody_s_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same `_theirs` the gate uses, so "clean" means the same thing to the thing that merges
    and the thing that closes a session."""
    monkeypatch.setattr(
        land, "_git", lambda cwd, *args, **rest: (0, "?? .claude/worktrees/a-branch/")
    )

    assert land.nothing_uncommitted("/tmp/anywhere")[0]


# --- and the pass ------------------------------------------------------------------------------------
def _a_row(project_key: str, said: str, status: str = "idle", quiet_ms: int = LONG_ENOUGH) -> Any:
    from types import SimpleNamespace

    session = Session(
        pid=1,
        procStart="1",
        sessionId="0f8cf805-a691-4599-9565-4211709833c0",
        cwd="/tmp/thing",
        name="biba",
        kind="interactive",
        version="1.0.0",
        status=status,
        updatedAt=0,
        statusUpdatedAt=now_ms() - quiet_ms,
    )
    tail = SimpleNamespace(last_entry=SimpleNamespace(role="assistant", text=said))
    return SimpleNamespace(session=session, tail=tail, project_key=project_key)


async def _switched_on(
    desk: Store, monkeypatch: pytest.MonkeyPatch, clean: bool = True
) -> list[str]:
    await desk.tidy_sessions("dir:/tmp/thing", on=True)
    await desk.keep_canary("0f8cf805", "canary-abc")
    monkeypatch.setattr(
        land, "nothing_uncommitted", lambda cwd: (clean, "clean" if clean else "dirty")
    )
    stopped: list[str] = []

    def stop(agent_id: str) -> object:
        stopped.append(agent_id)
        from agent_desk.dispatch import Started

        return Started(True, agent_id=agent_id)

    monkeypatch.setattr(autostart.dispatch, "stop", stop)
    return stopped


async def test_a_session_that_lost_its_canary_is_closed(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped = await _switched_on(desk, monkeypatch)

    closed = await autostart.tidy_lost_canaries(
        desk, [_a_row("dir:/tmp/thing", "I did the thing.")]
    )

    assert closed == ["0f8cf805"]
    assert stopped == ["0f8cf805"]


async def test_one_that_is_still_signing_is_left_alone(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped = await _switched_on(desk, monkeypatch)

    closed = await autostart.tidy_lost_canaries(
        desk, [_a_row("dir:/tmp/thing", "canary-abc: I did the thing.")]
    )

    assert closed == [] and stopped == []


async def test_one_with_uncommitted_work_is_left_alone(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped = await _switched_on(desk, monkeypatch, clean=False)

    await autostart.tidy_lost_canaries(desk, [_a_row("dir:/tmp/thing", "I did the thing.")])

    assert stopped == []


async def test_a_project_nobody_switched_on_is_not_read_at_all(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No switch, no reading, no thread — which is every console until somebody presses it."""
    read: list[str] = []
    monkeypatch.setattr(land, "nothing_uncommitted", lambda cwd: (read.append(cwd), (True, ""))[1])

    assert await autostart.tidy_lost_canaries(desk, [_a_row("dir:/tmp/thing", "x")]) == []
    assert read == []


async def test_a_session_this_console_never_told_to_sign_is_not_touched(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unsigned reply from anybody else's session means nothing at all, and closing one on the
    strength of it would be closing a stranger's work."""
    await desk.tidy_sessions("dir:/tmp/thing", on=True)
    stopped: list[str] = []
    monkeypatch.setattr(autostart.dispatch, "stop", lambda agent_id: stopped.append(agent_id))

    await autostart.tidy_lost_canaries(desk, [_a_row("dir:/tmp/thing", "I did the thing.")])

    assert stopped == []


async def test_a_session_in_another_project_is_not_touched(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped = await _switched_on(desk, monkeypatch)

    await autostart.tidy_lost_canaries(desk, [_a_row("dir:/tmp/other", "I did the thing.")])

    assert stopped == []


async def test_a_tick_reads_the_board_only_where_the_switch_is_on(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`rows=None` is the ordinary case and means "read it if it is needed" — and it is needed only
    where somebody pressed the switch, because reading the board is a registry read and a
    transcript tail per session (docs/adr/0012)."""
    read: list[int] = []
    from agent_desk.web import routes as real

    monkeypatch.setattr(real, "board", lambda: (read.append(1), ([], []))[1])

    assert await autostart.tick(desk, live=set(), rows=None) is None
    assert read == []

    await desk.tidy_sessions("dir:/tmp/thing", on=True)
    await autostart.tick(desk, live=set(), rows=None)
    assert read == [1]


async def test_a_board_handed_in_is_the_one_used(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller that has already read it passes it in, and nothing reads it twice."""
    stopped = await _switched_on(desk, monkeypatch)
    from agent_desk.web import routes as real

    def never() -> object:  # pragma: no cover — reaching it is the failure
        raise AssertionError("the board was read again")

    monkeypatch.setattr(real, "board", never)

    await autostart.tick(desk, live=set(), rows=[_a_row("dir:/tmp/thing", "I did the thing.")])

    assert stopped == ["0f8cf805"]


async def test_the_loop_calls_a_tick_and_nothing_else(desk: Store) -> None:
    """A loop that did work of its own before the tick is a loop a test cannot stand in for — and
    standing in for it is how the cancellation rule is tested at all. Found by that test hanging
    for ever when the board read was put in the loop."""
    source = pathlib.Path(autostart.__file__).read_text(encoding="utf-8")
    body = source[source.index("async def run(store: Store) -> None:") :]

    assert "await tick(store)" in body


# --- and the switch -----------------------------------------------------------------------------------
async def test_the_switch_is_its_own_and_starts_off(desk: Store) -> None:
    assert not (await desk.autostart("dir:/tmp/thing")).tidying

    await routes.switch_tidying(_a_form({"key": "dir:/tmp/thing", "tidying": "yes"}))
    assert (await desk.autostart("dir:/tmp/thing")).tidying

    await routes.switch_tidying(_a_form({"key": "dir:/tmp/thing", "tidying": "no"}))
    assert not (await desk.autostart("dir:/tmp/thing")).tidying


async def test_switching_it_on_does_not_arm_the_project_for_anything_else(desk: Store) -> None:
    """Three switches, three permissions. "Close a session that stopped signing" is a different
    thing to allow from "start what I queued"."""
    await desk.tidy_sessions("dir:/tmp/thing", on=True)

    arming = await desk.autostart("dir:/tmp/thing")
    assert arming.tidying
    assert not arming.armed
    assert not arming.exploring


async def test_the_panel_says_what_it_will_do_before_it_is_pressed(desk: Store) -> None:
    said = await routes.render_project("dir:/tmp/thing")

    assert "Close sessions that lost the canary" in said
    assert "only irreversible thing" in said


async def test_and_says_the_four_conditions_once_it_is_on(desk: Store) -> None:
    await desk.tidy_sessions("dir:/tmp/thing", on=True)

    said = await routes.render_project("dir:/tmp/thing")

    for one in ("stopped signing", "idle", "half an hour", "clean"):
        assert one in said


async def test_a_project_switched_on_only_for_this_is_not_armed_for_anything_else(
    desk: Store,
) -> None:
    """Three switches are three permissions, and the readers have to be three as well.

    Found by the gate hanging: returning a tidying project from `armed_projects` put it through the
    whole of the loop — the queue, the tracker's network calls, the exploration — on the strength
    of a switch that says nothing about any of them.
    """
    await desk.tidy_sessions("dir:/tmp/thing", on=True)

    assert [one.repo_key for one in await desk.tidying_projects()] == ["dir:/tmp/thing"]
    assert await desk.armed_projects() == []


async def test_a_tick_starts_nothing_for_a_project_that_is_only_tidying(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The consequence of the above, asserted where it bit: a tick must not reach the queue, and
    must not reach anybody's tracker, for a switch that is about closing sessions."""
    await desk.tidy_sessions("dir:/tmp/thing", on=True)
    await desk.queue_task(
        repo_key="dir:/tmp/thing",
        cwd="/tmp/thing",
        title="a job",
        instruction="do it",
        source_kind="idea",
    )

    def never(*args: object, **rest: object) -> object:  # pragma: no cover — reaching it is
        raise AssertionError("a tick reached the queue for a project nobody armed")

    monkeypatch.setattr(autostart, "_start", never)

    assert await autostart.tick(desk, live=set(), rows=None) is None
    assert (await desk.tasks())[0].started_at is None


async def test_a_console_where_nobody_pressed_the_switch_pays_nothing_for_it(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The board is a registry read and a transcript tail per session. A console that read it every
    tick for a feature nobody switched on would be charging everybody for one person's switch."""
    read: list[int] = []
    monkeypatch.setattr(autostart, "routes", None, raising=False)

    from agent_desk.web import routes as real

    monkeypatch.setattr(real, "board", lambda: (read.append(1), ([], []))[1])

    assert await autostart._the_board(desk) is None
    assert read == []


async def test_and_reads_it_where_somebody_did(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    await desk.tidy_sessions("dir:/tmp/thing", on=True)
    from agent_desk.web import routes as real

    monkeypatch.setattr(real, "board", lambda: ([_a_row("dir:/tmp/thing", "x")], []))

    said = await autostart._the_board(desk)

    assert said is not None and len(said) == 1


async def test_a_board_that_cannot_be_read_tidies_nothing(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    await desk.tidy_sessions("dir:/tmp/thing", on=True)
    from agent_desk.web import routes as real

    def broken() -> object:
        raise OSError("the registry is gone")

    monkeypatch.setattr(real, "board", broken)

    assert await autostart._the_board(desk) is None


# --- and the whole of it at once -------------------------------------------------------------------
@pytest.mark.unit
def test_the_only_irreversible_thing_says_yes_to_exactly_one_shape() -> None:
    """The input space of this decision is small enough to state rather than sample, and what it
    guards — «единственное необратимое действие во всей консоли» — is worth stating.

    Four conditions and a clock, enumerated: `yes` is true for every combination where all five
    hold and for no other, and no answer is ever wordless — a card that says no and not why sends
    somebody to the session they were about to close to find out.
    """
    quiet = tidying.QUIET_FOR_MS
    space = list(
        itertools.product(
            (True, False),
            (True, False),
            ("idle", "busy", "shell", "unknown", ""),
            (True, False),
            (-1, 0, 60_000, quiet - 60_001, quiet - 1, quiet, quiet + 1, 10 * quiet),
        )
    )

    said = {
        one: tidying.may_close(
            armed=one[0], canary_lost=one[1], status=one[2], clean=one[3], idle_for_ms=one[4]
        )
        for one in space
    }

    assert all(answer.why.strip() for answer in said.values())
    allowed = {one for one in space if one[0] and one[1] and one[2] == "idle" and one[3]}
    allowed = {one for one in allowed if one[4] >= quiet}
    assert {one for one, answer in said.items() if answer.yes} == allowed


@pytest.mark.unit
def test_the_wait_never_counts_down_to_nothing_and_stays_there() -> None:
    """Floor division says "0 more minutes" for the whole last minute, against a card that is
    refusing to close the session — which reads as the console being stuck rather than waiting."""
    for left_ms in (1, 1000, 59_999, 60_000):
        why = _may(idle_for_ms=tidying.QUIET_FOR_MS - left_ms).why

        assert "0 more" not in why
        assert "1 more minute" in why or "2 more minutes" in why

    assert "1 more minute'" not in _may(idle_for_ms=0).why  # and it is not always one, either
    assert "30 more minutes" in _may(idle_for_ms=0).why
