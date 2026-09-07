"""What the asking costs, and the ceiling it stops at (043-spending.sql).

"У автозапуска есть бюджет в час на агентов. У вызовов модели нет ничего… Это та вещь, отсутствие
которой обнаруживается в конце месяца."

Two properties matter more than the arithmetic. The count must survive a restart, because this
console is normally run with `--reload` and a tally in memory is a ceiling that a saved file walks
straight through. And the number must be what the run reported rather than anything this program
worked out — a cost this console computed would be a guess presented beside facts, which is the
fifth rule of CLAUDE.md with a currency symbol on it.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import pytest
from agent_desk.answer import session
from agent_desk.config import Settings
from agent_desk.store.repo import Store
from sqlalchemy import text


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


@pytest.fixture
def tallying(desk: Store) -> AsyncIterator[Store]:
    session.tally.attach(desk)
    yield desk
    session.tally.attach(None)


# --- counting ------------------------------------------------------------------------------------
@pytest.mark.unit
async def test_what_the_runs_reported_is_what_is_counted(desk: Store) -> None:
    await desk.note_spend(0.064166)
    await desk.note_spend(0.10)

    assert await desk.spent_today() == pytest.approx(0.164166)


@pytest.mark.unit
async def test_a_run_that_reported_nothing_is_not_counted_as_free(desk: Store) -> None:
    """A row of zeroes would make "the run did not say" and "the run was free" the same fact, and
    the first of those is a gap in the counter somebody should be able to see."""
    await desk.note_spend(0.0)
    await desk.note_spend(-1.0)

    async with desk.engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM spend"))).scalar() == 0


@pytest.mark.unit
async def test_yesterday_is_not_today(desk: Store) -> None:
    """The ceiling is a daily one, so what a day is has to be right or it is not a ceiling."""
    await desk.note_spend(5.0)
    yesterday = datetime.now().astimezone() - timedelta(days=1)
    async with desk.engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO spend (id, at, usd) VALUES ('old', :at, 40.0)"),
            {"at": int(yesterday.timestamp() * 1000)},
        )

    assert await desk.spent_today() == pytest.approx(5.0)


@pytest.mark.unit
async def test_the_day_starts_at_midnight_where_the_person_is(desk: Store) -> None:
    """Local rather than UTC. A console in Buenos Aires whose day rolled over at nine in the
    evening would be a counter nobody could read, and a ceiling that lifted then would be worse."""
    just_after_midnight = (
        datetime.now().astimezone().replace(hour=0, minute=0, second=30, microsecond=0)
    )
    async with desk.engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO spend (id, at, usd) VALUES ('early', :at, 3.0)"),
            {"at": int(just_after_midnight.timestamp() * 1000)},
        )

    assert await desk.spent_today() == pytest.approx(3.0)


@pytest.mark.unit
async def test_the_count_survives_the_console_being_restarted(tmp_path: pathlib.Path) -> None:
    """The whole reason this is a table. A tally in memory is a ceiling that `--reload` walks
    through, and this console is normally run with `--reload`."""
    where = tmp_path / "agent-desk.db"
    first = Store(where)
    await first.open()
    await first.note_spend(7.5)
    await first.close()

    second = Store(where)
    await second.open()
    try:
        assert await second.spent_today() == pytest.approx(7.5)
    finally:
        await second.close()


# --- the ceiling ---------------------------------------------------------------------------------
@pytest.mark.unit
async def test_under_the_ceiling_nothing_is_said(
    tallying: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session, "settings", Settings(daily_usd=25.0))
    await tallying.note_spend(1.0)

    assert await session.tally.stop_here() == ""


@pytest.mark.unit
async def test_at_the_ceiling_it_says_the_number_the_limit_and_how_to_raise_it(
    tallying: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Консоль останавливается и **говорит**". A sentence rather than a boolean, because what
    somebody needs at that moment is all three of those."""
    monkeypatch.setattr(session, "settings", Settings(daily_usd=2.0))
    await tallying.note_spend(2.5)

    why = await session.tally.stop_here()

    assert "2.50" in why and "2.00" in why
    assert "AGENT_DESK_DAILY_USD" in why


@pytest.mark.unit
async def test_a_ceiling_of_zero_is_no_ceiling(
    tallying: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Somebody who would rather find out at the end of the month can, and the way to say so is
    one number rather than a second setting that means "and I mean it"."""
    monkeypatch.setattr(session, "settings", Settings(daily_usd=0.0))
    await tallying.note_spend(9999.0)

    assert await session.tally.stop_here() == ""


@pytest.mark.unit
async def test_with_nothing_attached_nothing_is_counted_and_nothing_is_stopped() -> None:
    """A runner used outside the console — a test, a script — must still run."""
    session.tally.attach(None)

    assert await session.tally.stop_here() == ""
    await session.tally.note(5.0)


@pytest.mark.unit
def test_the_ceiling_ships_set_rather_than_off() -> None:
    """ "No ceiling by default" reproduces the problem: a console nobody configured is exactly the
    one whose bill arrives as a surprise."""
    assert Settings().daily_usd > 0


@pytest.mark.unit
def test_being_out_of_budget_reads_as_the_engine_being_unavailable() -> None:
    """So a console out of budget reaches a second engine if one is configured, through the
    machinery that is already there — rather than stopping with a free local model beside it."""
    assert session.unavailable("the day's budget is spent: $30.00 of $25.00")


@pytest.mark.unit
def test_the_check_is_where_the_call_is_made_and_not_above_it() -> None:
    """In `_run`, on the engine that costs money. Raised one level up it would stop the console
    before the fallback that exists for exactly this."""
    import ast

    source = pathlib.Path(session.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    inside = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
        for call in ast.walk(node)
        if isinstance(call, ast.Attribute) and call.attr == "stop_here"
    }

    assert inside == {"_run"}, f"the ceiling is checked in {inside or 'nowhere'}, not in _run"


# --- and it reaches both ends --------------------------------------------------------------------
@pytest.mark.unit
async def test_the_cost_is_taken_from_the_run_that_reported_it(
    tallying: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recorded, not computed. This console does not know a rate card and must not learn one: a
    price it worked out would be a guess standing next to facts."""
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        'printf \'{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}\\n\'\n'
        'printf \'{"type":"result","total_cost_usd":0.064166,"result":"hi"}\\n\'\n'
    )
    fake.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(fake), daily_usd=25.0))

    assert [chunk async for chunk in session.stream_answer("a question")] == ["hi"]
    assert await tallying.spent_today() == pytest.approx(0.064166)


@pytest.mark.unit
async def test_a_run_that_failed_after_spending_still_spent_it(
    tallying: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cost is read before the error is raised. A run that burned three dollars and then said
    it had gone wrong has burned three dollars, and a ceiling that only counted successes would be
    walked through by whatever was going wrong repeatedly."""
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        'printf \'{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}\\n\'\n'
        'printf \'{"type":"result","is_error":true,"subtype":"went wrong","total_cost_usd":3.0}\\n\'\n'
    )
    fake.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(fake), daily_usd=25.0))

    with pytest.raises(session.AnswerFailed):
        [chunk async for chunk in session.stream_answer("a question")]

    assert await tallying.spent_today() == pytest.approx(3.0)


@pytest.mark.unit
async def test_a_run_whose_cost_cannot_be_read_is_counted_as_nothing(
    tallying: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI's shape is not a contract (docs/adr/0004). A cost that does not parse leaves the
    counter where it was, which reads as "the run did not say" — the honest answer."""
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        'printf \'{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}\\n\'\n'
        'printf \'{"type":"result","total_cost_usd":"three dollars","result":"hi"}\\n\'\n'
    )
    fake.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(fake), daily_usd=25.0))

    assert [chunk async for chunk in session.stream_answer("a question")] == ["hi"]
    assert await tallying.spent_today() == 0.0


@pytest.mark.unit
async def test_over_the_ceiling_the_engine_is_never_started(
    tallying: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stopping after the money is spent is not a ceiling."""
    ran = tmp_path / "it-ran"
    fake = tmp_path / "claude"
    fake.write_text(f"#!/bin/sh\ntouch {ran}\n")
    fake.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(fake), daily_usd=1.0))
    await tallying.note_spend(1.5)

    with pytest.raises(session.AnswerFailed, match="budget"):
        [chunk async for chunk in session.stream_answer("a question")]

    assert not ran.exists(), "the run started anyway, which is the money already spent"


@pytest.mark.unit
async def test_the_number_is_on_the_board(desk: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """ "Нужен видимый счётчик". Behind a link is not visible: the complaint is about a number
    nobody was shown, and a page nobody opens shows nobody anything."""
    from agent_desk.web import routes

    monkeypatch.setattr(routes, "store", desk)
    await desk.note_spend(3.25)

    html = routes.render_board(spent=await routes.board_spent())

    assert "$3.25" in html


@pytest.mark.unit
async def test_the_ceiling_is_only_named_once_it_is_worth_thinking_about(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A counter that reads "$0.14 of $25.00" all day is a counter people stop reading, and this
    one exists because somebody was not reading a number that was never there."""
    from agent_desk.web import routes

    monkeypatch.setattr(routes, "store", desk)
    monkeypatch.setattr(routes, "settings", Settings(daily_usd=20.0))

    await desk.note_spend(1.0)
    quiet = routes.render_board(spent=await routes.board_spent())
    assert "$1.00 today" in quiet and "of $20.00" not in quiet

    await desk.note_spend(14.0)
    close = routes.render_board(spent=await routes.board_spent())
    assert "of $20.00" in close and "spend-close" in close

    await desk.note_spend(10.0)
    stopped = routes.render_board(spent=await routes.board_spent())
    assert "at today's ceiling" in stopped and "spend-stopped" in stopped


@pytest.mark.unit
async def test_a_board_rendered_without_the_number_shows_no_number(desk: Store) -> None:
    """Rather than a confident `$0.00`, which is a different claim: one says "nobody read it" and
    the other says "nothing was spent"."""
    from agent_desk.web import routes

    assert "today" not in routes.render_board()


# --- and it cannot take an answer down with it ---------------------------------------------------
@pytest.mark.unit
async def test_a_tally_that_cannot_be_read_lets_the_question_through(
    tmp_path: pathlib.Path,
) -> None:
    """A ceiling is a fuse, not part of the path an answer travels.

    This is checked from inside the run, where nothing above it catches anything but `AnswerFailed`
    — so an exception here left the block `running` for ever, which is exactly the state the crash
    rule exists to prevent, reachable from a counter. Found as a test that passed alone and failed
    in the suite, with a store closed under it.
    """
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    await store.close()
    session.tally.attach(store)
    try:
        assert await session.tally.stop_here() == ""
        await session.tally.note(1.0)
    finally:
        session.tally.attach(None)


@pytest.mark.unit
async def test_a_run_still_answers_when_the_tally_is_broken(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the rule above, end to end: the answer arrives."""
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        'printf \'{"type":"assistant","message":{"content":[{"type":"text","text":"an answer"}]}}\\n\'\n'
        'printf \'{"type":"result","total_cost_usd":0.5,"result":"an answer"}\\n\'\n'
    )
    fake.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(fake), daily_usd=25.0))

    broken = Store(tmp_path / "gone.db")
    await broken.open()
    await broken.close()
    session.tally.attach(broken)
    try:
        assert [c async for c in session.stream_answer("q")] == ["an answer"]
    finally:
        session.tally.attach(None)
