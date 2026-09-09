"""A card hung on an output that says one of two things about it (01M1XC1DBS2JZKFWZCVQW29JM1).

"Временный блок-проверка, в первой итерации берёт вводный вопрос/карточку + то что мы получили от
сервиса и возвращает одно из двух: 1 — всё корректно, 2 — вернулась какая-то дичь."

Two inputs and one verdict. The two inputs turn out to be one card: an answer card already carries
both halves of its exchange, so a check joined to one has everything it needs and no second kind of
wire had to be invented.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk import checking
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
BOARD = HERE / "agent_desk" / "web" / "templates" / "board.html"
CARD = HERE / "agent_desk" / "web" / "templates" / "_card_check.html"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def _a_form(**fields: str) -> object:
    body = "&".join(f"{name}={value}" for name, value in fields.items()).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()


async def _an_answer(desk: Store, asked: str, got: str) -> str:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input=asked, thread_set_by="human"
    )
    await desk.finish_block(block.id, got)
    return block.id


# --- reading a verdict out of a reply ------------------------------------------------------------
def test_yes_and_no_in_either_language() -> None:
    assert checking.read_verdict("yes — it answers the question") == (
        True,
        "it answers the question",
    )
    assert checking.read_verdict("нет: там нет ни слова про миграцию")[0] is False


def test_a_reply_that_decided_nothing_is_not_a_failure() -> None:
    """A model that answered something else has not made a judgement, and writing that down as "it
    did not pass" is a verdict invented from silence — the fifth rule, in the one place where
    inventing one is easiest."""
    assert checking.read_verdict("I would need to see the migration first") is None
    assert checking.read_verdict("") is None


def test_a_verdict_with_no_reason_still_says_something() -> None:
    assert checking.read_verdict("yes") == (True, "it does")
    assert checking.read_verdict("no") == (False, "it does not")


def test_the_condition_is_asked_last() -> None:
    """A model that has read the question and the answer before it reads what to look for is one
    that judges rather than pattern-matches."""
    said = checking.judgement_prompt("what is it", "it is a duck", "mentions a bird")

    assert said.index("what is it") < said.index("it is a duck") < said.index("mentions a bird")
    assert "yes or no" in said


# --- the card ------------------------------------------------------------------------------------
async def test_a_check_keeps_its_name_and_its_condition(desk: Store) -> None:
    made = await desk.add_check_card("no errors", "does not contain ERROR")

    again = await desk.check_card(made.id)
    assert again is not None
    assert (again.label, again.said) == ("no errors", "does not contain ERROR")
    assert again.name == f"check:{made.id}"


async def test_nobody_has_pressed_it_is_not_a_third_verdict(desk: Store) -> None:
    made = await desk.add_check_card("a check", "is JSON")

    again = await desk.check_card(made.id)
    assert again is not None and again.verdict == ""


async def test_editing_the_condition_clears_the_verdict(desk: Store) -> None:
    """A card saying "passed" under a condition somebody has just changed is a card answering a
    question nobody asked."""
    made = await desk.add_check_card("a check", "is JSON")
    await desk.card_checked(made.id, passed=True, why="it is JSON", judged=False)

    await desk.set_check_card(made.id, label="a check", said="shorter than 40")

    again = await desk.check_card(made.id)
    assert again is not None and again.verdict == "" and again.why == ""


# --- and pressing it -----------------------------------------------------------------------------
async def test_a_condition_a_rule_can_settle_costs_nothing(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The four forms `checking.py` already reads are decided here and now. A check that went to a
    model to find out whether a string contains another string is one nobody would press twice."""

    async def never(said: str):  # type: ignore[no-untyped-def]
        raise AssertionError("it asked the model")
        yield ""

    monkeypatch.setattr(routes.answer_session, "stream_answer", never)
    block = await _an_answer(desk, "give me the log", "everything fine")
    made = await desk.add_check_card("no errors", "does not contain ERROR")

    answer = await routes.run_a_check(_a_form(id=made.id, on=f"answer:{block}"))

    said = json.loads(answer.body)
    assert said["verdict"] == "passed"
    assert said["judged"] is False, "a rule was settled by asking the model"


async def test_a_condition_that_is_a_sentence_is_asked(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "It passed" from a regular expression and "it passed" from a model are not the same claim,
    so the card records which it has."""
    asked: list[str] = []

    async def replies(said: str):  # type: ignore[no-untyped-def]
        asked.append(said)
        yield "no — it never says what the migration does"

    monkeypatch.setattr(routes.answer_session, "stream_answer", replies)
    block = await _an_answer(desk, "what does 042 do", "I would have to look")
    made = await desk.add_check_card("answers it", "it answers the question that was asked")

    answer = await routes.run_a_check(_a_form(id=made.id, on=f"answer:{block}"))

    said = json.loads(answer.body)
    assert said["verdict"] == "failed"
    assert said["judged"] is True
    assert "what does 042 do" in asked[0] and "I would have to look" in asked[0]


async def test_a_verdict_survives_the_page(desk: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stored rather than recomputed: a check that re-asks the model on every render is one that
    quietly changes its mind between refreshes."""
    block = await _an_answer(desk, "give me the log", "everything fine")
    made = await desk.add_check_card("no errors", "does not contain ERROR")

    await routes.run_a_check(_a_form(id=made.id, on=f"answer:{block}"))

    again = await desk.check_card(made.id)
    assert again is not None and again.verdict == "passed" and again.at > 0


async def test_a_check_joined_to_nothing_says_so(desk: Store) -> None:
    made = await desk.add_check_card("no errors", "does not contain ERROR")

    answer = await routes.run_a_check(_a_form(id=made.id, on=""))

    assert "Join it to an answer" in answer.body.decode()


async def test_an_answer_that_has_not_come_back_is_not_checked(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="ask", thread_set_by="human"
    )
    made = await desk.add_check_card("no errors", "does not contain ERROR")

    answer = await routes.run_a_check(_a_form(id=made.id, on=f"answer:{block.id}"))

    assert "nothing in it yet" in answer.body.decode()
    assert (await desk.check_card(made.id)).verdict == ""  # type: ignore[union-attr]


async def test_a_model_that_decided_nothing_records_nothing(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def waffles(said: str):  # type: ignore[no-untyped-def]
        yield "It depends what you mean by correct."

    monkeypatch.setattr(routes.answer_session, "stream_answer", waffles)
    block = await _an_answer(desk, "what does it do", "something")
    made = await desk.add_check_card("answers it", "it answers the question")

    answer = await routes.run_a_check(_a_form(id=made.id, on=f"answer:{block}"))

    assert "nothing was decided" in answer.body.decode()
    assert (await desk.check_card(made.id)).verdict == ""  # type: ignore[union-attr]


# --- and how it reads ----------------------------------------------------------------------------
def test_the_verdict_says_how_it_was_reached() -> None:
    markup = CARD.read_text(encoding="utf-8")

    assert "judged by the answer engine" in markup
    assert "decided by the rule on the card" in markup


def test_neither_verdict_is_only_a_colour() -> None:
    """A bench read in a hurry is read by shape."""
    css = (HERE / "agent_desk" / "web" / "static" / "console.css").read_text(encoding="utf-8")

    assert '.check-verdict.passed strong::before { content: "✓ "; }' in css
    assert '.check-verdict.failed strong::before { content: "✗ "; }' in css
    assert "it did not pass" in CARD.read_text(encoding="utf-8")


def test_it_reads_an_answer_and_says_which_one() -> None:
    """A control that reaches for something different depending on the state of the bench has to
    say which — the same rule the button follows, through the same line."""
    source = _code()

    assert "function whatItChecks(" in source
    assert "name.startsWith('answer:')" in source
    assert 'data-add="check"' in BOARD.read_text(encoding="utf-8")


async def test_a_check_joined_to_two_answers_refuses_to_guess(desk: Store) -> None:
    """Found in a browser: joined to two, it read the first and said nothing about the choice. One
    verdict about one of two things, with no way to tell which."""
    first = await _an_answer(desk, "one", "fine")
    second = await _an_answer(desk, "two", "also fine")
    made = await desk.add_check_card("no errors", "does not contain ERROR")

    answer = await routes.run_a_check(_a_form(id=made.id, on=f"answer:{first}%2Canswer:{second}"))

    assert "joined to 2 answers" in answer.body.decode()
    assert (await desk.check_card(made.id)).verdict == ""  # type: ignore[union-attr]


def test_the_card_says_so_before_it_is_pressed() -> None:
    """A control that will refuse should say so where somebody can read it, not when they press."""
    assert "A check reads one — rub out the others." in _code()


# --- and what a verdict does to the card ---------------------------------------------------------
def _body_of(name: str) -> str:
    source = _code()
    start = source.index(f"function {name}(")
    return source[start : source.index("\n}\n", start)]


def test_a_check_that_passed_goes_quiet() -> None:
    """ "Карточка проверки потухает и становится серой и неактивной." A check that passed has
    nothing left to say and should stop asking to be read."""
    body = _body_of("showCheck")
    css = (HERE / "agent_desk" / "web" / "static" / "console.css").read_text(encoding="utf-8")

    assert "classList.toggle('checked'" in body
    assert "button.hidden = !isCheck || Boolean(verdict);" in body, "it can still be pressed"
    assert ".pin.checked { opacity:" in css


def test_it_does_not_disappear() -> None:
    """ "Но и исчезать не должна: то, что ответ был проверен, — это факт, который завтра
    пригодится." Dimmed, and back to full weight under the pointer."""
    css = (HERE / "agent_desk" / "web" / "static" / "console.css").read_text(encoding="utf-8")

    assert ".pin.checked:hover, .pin.checked:focus-within { opacity: 1; }" in css
    assert 'content: " · checked";' in css


def test_a_check_that_failed_stays_open() -> None:
    """It is the thing somebody has to act on, and folding it away would hide the sentence saying
    what to do."""
    body = _body_of("runTheCheck")

    assert "if (said.verdict === 'passed') setView(holder, 'hint');" in body


async def test_the_card_renders_what_it_checks_and_what_it_decided(desk: Store) -> None:
    """The condition is on the card because a check whose condition you cannot read is one whose
    verdict nobody trusts — the same argument the button's request is on its card."""
    made = await desk.add_check_card("no errors", "does not contain ERROR")
    await desk.card_checked(made.id, passed=True, why="it does not contain “ERROR”", judged=False)

    answer = await routes.card("check", made.id)
    said = answer.body.decode()

    assert "does not contain ERROR" in said
    assert "it passed" in said
    assert "decided by the rule on the card" in said


async def test_a_check_that_is_gone_says_so_rather_than_breaking(desk: Store) -> None:
    answer = await routes.card("check", "01M1NOSUCHCHECK")

    assert answer.status_code == 404
    assert "not here any more" in answer.body.decode()
