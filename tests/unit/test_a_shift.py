"""A shift survives its own compaction (01M21KTYE2Y47FWTDGHP4N7XV1).

«Эта сессия сжималась дважды. Каждый раз я терял детали и заново выяснял, где нахожусь: перечитывал
пул, идею, код.»

Everything needed is already in this database. What was missing is one thread with time on it, short
enough to be the first thing read afterwards.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import standing
from agent_desk.store.repo import SHIFT_ENDS_AFTER_MS, Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


# --- it starts by itself and ends on silence -------------------------------------------------
async def test_the_first_line_opens_a_shift(desk: Store) -> None:
    """ "Не кнопкой." A shift somebody has to start is one they start after the part they wanted
    it for."""
    assert await desk.the_shift() is None

    await desk.note_in_the_shift("note", "began on the reader")

    going = await desk.the_shift()
    assert going is not None and going.note == "began on the reader"


async def test_the_lines_of_one_stretch_stay_together(desk: Store) -> None:
    await desk.note_in_the_shift("note", "one")
    await desk.note_in_the_shift("note", "two")

    going = await desk.the_shift()
    assert going is not None
    assert [step.said for step in await desk.shift_steps(going.id)] == ["one", "two"]


async def test_a_long_silence_ends_it_at_its_last_line(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closed where the work stopped, not where somebody noticed. The hours of silence were not
    work, and a shift that claims them reports a cost per idea that is a fiction."""
    from agent_desk.store import repo

    now = [1_000_000_000_000]
    monkeypatch.setattr(repo, "_now_ms", lambda: now[0])
    await desk.note_in_the_shift("note", "before lunch")
    stopped = now[0]

    now[0] += SHIFT_ENDS_AFTER_MS + 1
    await desk.note_in_the_shift("note", "the next day")

    going = await desk.the_shift()
    assert going is not None
    assert [step.said for step in await desk.shift_steps(going.id)] == ["the next day"]
    assert going.began_at == now[0]
    assert stopped < now[0]


# --- what writes into it ------------------------------------------------------------------------
async def test_closing_an_idea_writes_a_line(desk: Store) -> None:
    """Written by the thing that did it rather than assembled at the end — because the end is
    exactly the moment a context window runs out."""
    one = await desk.create_idea(text_="do the thing", summary="do the thing", source_kind="typed")

    await desk.set_idea_state(one.id, "done")

    going = await desk.the_shift()
    assert going is not None
    (step,) = await desk.shift_steps(going.id)
    assert step.what == "idea"
    assert one.id in step.said and "do the thing" in step.said


async def test_an_idea_that_is_merely_kept_writes_nothing(desk: Store) -> None:
    """A shift of every state change is a shift nobody reads."""
    one = await desk.create_idea(text_="do the thing", summary="do the thing", source_kind="typed")

    await desk.set_idea_state(one.id, "kept")

    assert await desk.the_shift() is None


async def test_a_commit_writes_a_line(desk: Store) -> None:
    one = await desk.create_idea(text_="do the thing", summary="do the thing", source_kind="typed")

    await desk.record_filing(idea_id=one.id, tracker="git", issue_key="4f2a1c", url="http://x/")

    going = await desk.the_shift()
    assert going is not None
    (step,) = await desk.shift_steps(going.id)
    assert step.what == "commit" and "4f2a1c" in step.said


async def test_a_gate_result_writes_a_line_either_way(desk: Store) -> None:
    """Red is the half that matters after a compaction, and it is the half a summary loses."""
    task = await desk.queue_task(
        repo_key="k", cwd="/tmp", title="a job", instruction="do it", source_kind="idea"
    )

    await desk.task_landed(task.id, "two tests failed", landed=False)

    going = await desk.the_shift()
    assert going is not None
    (step,) = await desk.shift_steps(going.id)
    assert step.what == "gate" and step.said.startswith("red")


# --- where it stopped ---------------------------------------------------------------------------
async def test_where_it_stopped_says_the_four_things(desk: Store) -> None:
    """ "Последняя незакрытая идея, последний коммит, состояние дерева, что было красным.\" """
    open_ = await desk.create_idea(text_="still to do", summary="still to do", source_kind="typed")
    done = await desk.create_idea(text_="done one", summary="done one", source_kind="typed")
    await desk.set_idea_state(done.id, "done")
    await desk.record_filing(idea_id=done.id, tracker="git", issue_key="4f2a1c", url="http://x/")
    task = await desk.queue_task(
        repo_key="k", cwd="/tmp", title="a job", instruction="do it", source_kind="idea"
    )
    await desk.task_landed(task.id, "two tests failed", landed=False)

    said = await standing.where_it_stopped(desk)

    assert open_.id in said
    assert "4f2a1c" in said
    assert "two tests failed" in said
    assert "not measured" in said


async def test_nothing_yet_says_so_rather_than_showing_an_empty_shape(desk: Store) -> None:
    assert "Nothing has happened yet" in await standing.where_it_stopped(desk)


async def test_a_green_gate_after_a_red_one_is_what_is_reported(desk: Store) -> None:
    task = await desk.queue_task(
        repo_key="k", cwd="/tmp", title="a job", instruction="do it", source_kind="idea"
    )
    await desk.task_landed(task.id, "two tests failed", landed=False)
    await desk.task_landed(task.id, "it merged", landed=True)

    assert "last green" in await standing.where_it_stopped(desk)


async def test_it_fits_in_one_look_and_names_what_did_not(desk: Store) -> None:
    """ "Жёсткая граница по длине, и то, что не влезло, называется числом." A reader who knows
    there are eleven more lines can ask; one who does not believes they have the whole thing."""
    for at in range(60):
        await desk.note_in_the_shift("note", f"line number {at} " + "x" * 200)

    said = await standing.where_it_stopped(desk)

    assert len(said) <= standing.MOST_CHARS
    assert "more line" in said
    assert "/shift" in said


def test_a_short_answer_is_left_exactly_as_it_is() -> None:
    assert standing.within("two\nlines") == "two\nlines"


def test_it_is_cut_on_a_line_boundary() -> None:
    """Half a sentence about a commit is worse than no sentence: a reader cannot tell a truncated
    fact from a short one."""
    said = standing.within("\n".join(f"line {n} " + "y" * 40 for n in range(40)), most=300)

    assert all(line.startswith(("line ", "…")) for line in said.splitlines())


# --- and the routes -----------------------------------------------------------------------------
async def test_the_route_answers_in_plain_text(desk: Store) -> None:
    """ "Маршрут, отдающий это как простой текст, а не как страницу." The reader is usually not a
    person with a browser."""
    await desk.note_in_the_shift("note", "began on the reader")

    back = await routes.where_it_stopped()

    assert back.media_type == "text/plain"
    assert b"<html" not in back.body


async def test_the_whole_shift_is_behind_the_number(desk: Store) -> None:
    """A ceiling with nowhere to go behind it is a ceiling that loses things."""
    for at in range(30):
        await desk.note_in_the_shift("note", f"line number {at}")

    back = await routes.the_whole_shift()

    assert b"line number 0" in back.body
    assert b"line number 29" in back.body


async def test_the_whole_shift_before_anything_has_happened(desk: Store) -> None:
    assert b"Nothing has happened yet" in (await routes.the_whole_shift()).body


# --- what a shift cost (01M21KTYGJEY662DRMDM8Z4YHM) ---------------------------------------------
async def test_the_cost_of_a_shift_adds_up_what_is_already_counted(desk: Store) -> None:
    """ "Ни одного нового измерения: вызовы модели уже считаются, шаги прогонов уже считаются."""
    await desk.note_in_the_shift("note", "started")
    going = await desk.the_shift()
    assert going is not None
    await desk.note_spend(0.25)
    run = await desk.start_run(cards=["step:one"], repo_key="", cwd="")
    await desk.set_run_step(run_id=run.id, name="step:one", state="done", usd=0.75)

    assert await desk.spent_since(going.began_at) == pytest.approx(1.0)


async def test_what_an_agent_spent_is_said_in_words_and_not_as_a_zero(desk: Store) -> None:
    """ "Ноль в этом месте — утверждение, что было бесплатно; «не измерено» — правда." (CLAUDE.md,
    rule five.)"""
    await desk.note_in_the_shift("note", "started")

    said = await standing.where_it_stopped(desk)

    assert "not zero, not measured" in said


@pytest.mark.parametrize(
    ("many", "expected"),
    [(1, "1 idea is open"), (2, "2 ideas are open"), (0, "0 ideas are open")],
)
async def test_it_counts_ideas_in_english(desk: Store, many: int, expected: str) -> None:
    """Found in the browser: it said "1 idea are open". A line somebody reads first thing after a
    compaction is a line that has to read."""
    await desk.note_in_the_shift("note", "started")
    for at in range(many):
        await desk.create_idea(text_=f"idea {at}", summary=f"idea {at}", source_kind="typed")

    assert expected in await standing.where_it_stopped(desk)
