"""A finished run, written out as the description of a change (01M1XED1D4F084PSWSSF960HZ7).

"Прогон знает: что просили, какие шаги прошли, что каждый сделал, какие развилки выбраны и почему,
что легло в ветку. Это и есть описание изменения — лучше, чем напишет человек по памяти через день.
Кнопка «сделать описание PR» на завершённом прогоне."
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk import describing
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _a_form(**fields: str) -> object:
    body = "&".join(f"{name}={value}" for name, value in fields.items()).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()


# --- what the prompt is made of --------------------------------------------------------------------
def test_every_line_of_what_happened_is_a_row_and_not_a_summary() -> None:
    """The model's job is the wording, not the content — which is the difference between a
    description somebody can check and one they have to believe."""
    said = describing.what_to_write(
        "make it faster",
        [describing.Step(label="read the log", state="done", made="found the hot loop")],
    )

    assert "make it faster" in said
    assert "- read the log: found the hot loop" in said


def test_what_did_not_run_is_named() -> None:
    """A reader who finds out later that half the drawing was skipped stops trusting the other
    half."""
    said = describing.what_to_write(
        "",
        [
            describing.Step(label="do it", state="done", made="done"),
            describing.Step(label="land it", state="held", detail="waiting for the release"),
        ],
    )

    assert "## What did not run" in said
    assert "land it: held — waiting for the release" in said


def test_a_run_nobody_wrote_a_request_for_says_so() -> None:
    """Rather than inventing a request nobody made."""
    said = describing.what_to_write("", [describing.Step(label="do it", state="done")])

    assert "Nothing was written down" in said


def test_it_is_told_not_to_describe_code_it_has_not_seen() -> None:
    """This console does not read the diff. A description that claimed to summarise the changes
    would be summarising a thing it never saw."""
    said = describing.what_to_write("x", [])

    assert "have not seen the code" in said


def test_one_step_that_reported_nothing_says_that_rather_than_being_dropped() -> None:
    said = describing.what_to_write("x", [describing.Step(label="do it", state="done")])

    assert "it reported nothing" in said


def test_a_long_report_is_shortened_rather_than_carried_whole() -> None:
    """A run of ten steps should not become a transcript."""
    said = describing.what_to_write(
        "x", [describing.Step(label="do it", state="done", made="y" * 900)]
    )

    assert len(said) < 900


# --- and the control -------------------------------------------------------------------------------
async def test_a_run_that_is_still_going_is_not_described(desk: Store) -> None:
    """ "A description of half a run is half a lie."" """
    run = await desk.start_run(cards="a", repo_key="k", cwd="/tmp")

    answer = await routes.describe_the_change(_a_form(run=run.id))

    assert "still going" in answer.body.decode()


async def test_a_finished_run_is_asked_as_a_gesture(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The words are the console's own, so there is nothing in them for the classifier to work out
    — and no card is drawn for a question nobody typed."""
    asked: list[tuple[str, bool]] = []

    thread = await desk.create_thread("a chat")

    async def caught(store: Store, typed: str, rows: object, **rest: object) -> object:
        asked.append((typed, bool(rest.get("a_gesture"))))
        return await desk.create_block(
            thread_id=thread.id, kind="question", input=typed, thread_set_by="human"
        )

    monkeypatch.setattr(routes.block_runs, "submit", caught)
    run = await desk.start_run(cards="a", repo_key="k", cwd="/tmp")
    await desk.set_run_step(run_id=run.id, name="step:a", state="done", made="it worked")
    await desk.end_run(run.id)

    answer = await routes.describe_the_change(_a_form(run=run.id))

    assert json.loads(answer.body)["asked"]
    (said, gesture) = asked[0]
    assert gesture is True
    assert "it worked" in said


async def test_a_run_that_is_gone_says_so(desk: Store) -> None:
    answer = await routes.describe_the_change(_a_form(run="01M1NOSUCHRUN"))

    assert "not here any more" in answer.body.decode()


def test_it_is_offered_only_on_a_finished_run() -> None:
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index("function lastFinishedRun(")
    body = source[start : source.index("\n}\n", start)]

    assert "!one.going && !one.waiting" in body
