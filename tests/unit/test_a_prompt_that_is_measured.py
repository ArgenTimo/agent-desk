"""Whether an edit to a prompt made it better (01M21KTYCKRH331SWJ1DY8AVA2).

«За эту смену я трижды правил `classify.kind_prompt` — восемьдесят строк инструкций, которые решают,
поднимется ли агент в воркдире. Проверить, стало ли лучше, было нечем: тесты утверждают ТЕКСТ
промпта, а не его поведение.»
"""

from __future__ import annotations

import pathlib
import urllib.parse
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk import checking, grading
from agent_desk.answer import classify
from agent_desk.store.repo import Block, Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit


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

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()


def _answers(reply: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []

    async def fake(prompt: str) -> AsyncIterator[str]:
        asked.append(prompt)
        yield reply

    monkeypatch.setattr(classify, "stream_answer", fake)
    return asked


async def _a_line(desk: Store, said: str, kind: str = "question") -> Block:
    thread = await desk.create_thread("a chat")
    return await desk.create_block(
        thread_id=thread.id, kind=kind, input=said, thread_set_by="classifier"
    )


# --- the seventh check form ------------------------------------------------------------------------
def test_a_check_can_ask_whether_the_answer_is_the_expected_one() -> None:
    """ "Проверка вида «равно ожидаемому» — где ожидаемое берётся из входа." What a run is measured
    against changes with every row, so it travels with the input rather than with the card."""
    check = checking.read("is the expected answer")

    assert check is not None and check.kind == "expected"
    assert checking.passes(check, "idea", expected="idea")[0]
    assert not checking.passes(check, "master", expected="idea")[0]


def test_it_is_written_the_way_somebody_says_it_in_either_language() -> None:
    for said in ("is the expected", "is the expected answer", "равно ожидаемому"):
        one = checking.read(said)
        assert one is not None and one.kind == "expected", said


def test_a_full_stop_and_a_capital_are_not_a_disagreement() -> None:
    """A reader that answers "idea." and one that answers "idea" have not disagreed."""
    check = checking.read("is the expected answer")
    assert check is not None

    assert checking.passes(check, "Idea.", expected="idea")[0]


def test_an_expected_check_with_nothing_expected_fails_rather_than_passes() -> None:
    """Passing on an empty expectation would make a whole set of rows count as correct."""
    check = checking.read("is the expected answer")
    assert check is not None

    passed, why = checking.passes(check, "idea", expected="")

    assert not passed
    assert "should have been" in why


def test_a_failure_says_what_it_said_and_what_the_answer_was() -> None:
    check = checking.read("is the expected answer")
    assert check is not None

    _, why = checking.passes(check, "master", expected="idea")

    assert "master" in why and "idea" in why


# --- the set, out of this console's own history ------------------------------------------------------
async def test_a_line_a_person_labelled_is_in_the_set(desk: Store) -> None:
    """ "Не хватает второй колонки — что это было на самом деле, — и она размечается один раз
    человеком.\" """
    block = await _a_line(desk, "бери в работу")
    await desk.label_block(block.id, "master")

    (row,) = grading.from_history([block], await desk.labels())

    assert (row.said, row.kind) == ("бери в работу", "master")


async def test_the_truth_is_kept_apart_from_what_the_classifier_decided(desk: Store) -> None:
    """A measurement that read the classifier's own answer as the truth would measure nothing."""
    block = await _a_line(desk, "бери в работу", kind="question")
    await desk.label_block(block.id, "master")

    (row,) = grading.from_history([block], await desk.labels())

    assert block.kind == "question"
    assert row.kind == "master"


async def test_a_line_nobody_labelled_is_not_in_the_set(desk: Store) -> None:
    block = await _a_line(desk, "бери в работу")

    assert grading.from_history([block], await desk.labels()) == []


async def test_a_block_a_person_already_corrected_is_a_label_nobody_types_twice(
    desk: Store,
) -> None:
    """ "Разметка берётся из уже исправленных блоков: `thread_set_by='human'` — это готовые метки."""
    thread = await desk.create_thread("a chat")
    corrected = await desk.create_block(
        thread_id=thread.id, kind="idea", input="a thought", thread_set_by="human"
    )
    untouched = await desk.create_block(
        thread_id=thread.id, kind="idea", input="another", thread_set_by="classifier"
    )

    said = grading.already_said([corrected, untouched])

    assert said == {corrected.id: "idea"}


async def test_an_empty_line_is_left_out_rather_than_counted_as_an_easy_row(desk: Store) -> None:
    """An empty line is not a decision the prompt has to get right."""
    block = await _a_line(desk, "   ")
    await desk.label_block(block.id, "question")

    assert grading.from_history([block], await desk.labels()) == []


def test_how_many_cards_it_was_asked_with_comes_off_the_context() -> None:
    """What somebody was pointing at is part of what they said, and the classifier is given it —
    so a measurement without it asks a different question from the one the console asks."""
    assert grading._cards_in("idea · a thought\nsession · biba (1 session)") == 2
    assert grading._cards_in("idea · a thought\nearlier · what did it do") == 1
    assert grading._cards_in("") == 0


# --- the measurement ---------------------------------------------------------------------------------
async def test_the_score_counts_what_matched_and_names_what_did_not(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Итог прогона: доля правильных, и список тех строк, на которых промпт ошибся." A number
    alone says a prompt got worse and not where, and where is what somebody edits."""
    _answers("question", monkeypatch)
    rows = [
        grading.Row(block_id="1", said="what is it doing", kind="question"),
        grading.Row(block_id="2", said="бери в работу", kind="master"),
    ]

    score = await grading.measure(rows)

    assert (score.right, score.of) == (1, 2)
    assert [one.said for one in score.wrong] == ["бери в работу"]
    assert score.wrong[0].got == "question" and score.wrong[0].wanted == "master"


async def test_it_asks_through_the_function_the_console_uses(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A measurement that reimplemented the call would measure a copy of the prompt."""
    asked = _answers("question", monkeypatch)

    await grading.measure([grading.Row(block_id="1", said="what is it doing", kind="question")])

    assert asked and "what is it doing" in asked[0]


async def test_nothing_labelled_says_so_rather_than_scoring_nothing_out_of_nothing() -> None:
    score = await grading.measure([])

    assert score.of == 0
    assert "no line has been labelled" in score.says


def test_only_so_many_rows_are_run() -> None:
    """Fifty calls is a minute and a few cents; five hundred is neither, and a measurement nobody
    runs measures nothing."""
    assert grading.MOST_ROWS == 50


# --- and it is kept beside the commit ------------------------------------------------------------------
async def test_a_score_is_recorded_against_the_commit(desk: Store) -> None:
    """ "Прогон, привязанный к коммиту, — это ответ на вопрос "моя правка промпта улучшила его или
    нет", а это единственный вопрос, ради которого всё и делается.\" """
    await desk.record_grade(what="kind", right_=41, of=50, commit_sha="4f2a1c9")

    (one,) = await desk.grades("kind")
    assert one.says == "41 of 50"
    assert one.commit_sha == "4f2a1c9"


async def test_the_previous_scores_are_shown_with_the_new_one(desk: Store) -> None:
    """ "Строка на карточке промпта: «в прошлый раз 41 из 50, в позапрошлый 46».\" """
    said = grading.as_text(
        grading.Score(right=44, of=50), [("4f2a1c9abc", "41 of 50"), ("b7ff002", "46 of 50")]
    )

    assert "44 of 50" in said
    assert "41 of 50 at 4f2a1c9" in said
    assert "46 of 50 at b7ff002" in said


def test_a_commit_that_cannot_be_read_is_empty_rather_than_guessed(tmp_path: pathlib.Path) -> None:
    """A measurement filed against the wrong commit answers "did my edit help" with somebody
    else's edit (CLAUDE.md, rule five)."""
    assert grading.at_the_commit(tmp_path) == ""


def test_it_reads_the_commit_of_this_repository() -> None:
    here = pathlib.Path(__file__).resolve().parents[2]

    assert len(grading.at_the_commit(here)) == 40


# --- the screen ------------------------------------------------------------------------------------------
async def test_the_screen_offers_a_button_per_kind(desk: Store) -> None:
    await _a_line(desk, "бери в работу")

    said = (await routes.labelling()).body.decode()

    assert "бери в работу" in said
    for kind in routes.LABELS:
        assert f'value="{kind}"' in said


def test_unsure_is_not_something_a_person_can_say_a_line_really_was() -> None:
    """It is the console saying it could not tell, which is never what a line actually was."""
    assert "unsure" not in routes.LABELS


async def test_pressing_a_kind_records_it_and_says_so(desk: Store) -> None:
    block = await _a_line(desk, "бери в работу")

    back = await routes.say_what_it_was(_a_form({"id": block.id, "kind": "master"}))

    assert await desk.labels() == {block.id: "master"}
    assert "master" in back.body.decode()


async def test_a_kind_that_is_not_one_of_them_writes_nothing(desk: Store) -> None:
    block = await _a_line(desk, "бери в работу")

    back = await routes.say_what_it_was(_a_form({"id": block.id, "kind": "unsure"}))

    assert back.status_code == 404
    assert await desk.labels() == {}


async def test_running_it_records_a_score_and_reports_the_wrong_ones(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers("question", monkeypatch)
    block = await _a_line(desk, "бери в работу")
    await desk.label_block(block.id, "master")

    said = (await routes.measure_the_classifier()).body.decode()

    (one,) = await desk.grades("kind")
    assert (one.right_, one.of) == (0, 1)
    assert "0 of 1" in said
    assert "master" in said


async def test_running_it_with_nothing_labelled_records_nothing(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row of zero out of zero in the history is a measurement that never happened, filed as one
    that did."""
    _answers("question", monkeypatch)
    await _a_line(desk, "бери в работу")

    await routes.measure_the_classifier()

    assert await desk.grades("kind") == []


# --- one mechanism, four readers ---------------------------------------------------------------
def test_every_decision_of_this_kind_is_named_with_what_measuring_it_would_take() -> None:
    """«`classify.about`, `showing.what_to_show`, `telling.read_shape` принимают решения такой же
    цены и измерены так же — никак. Один механизм, четыре набора.»

    The mechanism is `measure`, which takes the asking function. A reader listed without one is a
    reader whose *set* does not exist, and it says which set that would be: a set is labelling
    somebody does rather than code somebody writes, and a reader in this list with neither would
    report a score about nothing.
    """
    assert {one.what for one in grading.READERS} == {"kind", "about", "showing", "shape"}
    for one in grading.READERS:
        assert one.ask is not None or one.needs, one.what


async def test_the_measurement_takes_the_reader_rather_than_naming_one(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing the function is what makes this one mechanism: a second reader is a second `ask`,
    not a second copy of the counting."""

    async def always_an_idea(row: grading.Row) -> str:
        return "idea"

    rows = [
        grading.Row(block_id="1", said="a thought", kind="idea"),
        grading.Row(block_id="2", said="бери в работу", kind="master"),
    ]

    score = await grading.measure(rows, ask=always_an_idea)

    assert (score.right, score.of) == (1, 2)


def test_the_reader_being_measured_today_is_the_one_with_a_set() -> None:
    one = grading.reader("kind")

    assert one is not None and one.ask is not None
    assert grading.reader("nothing at all") is None
