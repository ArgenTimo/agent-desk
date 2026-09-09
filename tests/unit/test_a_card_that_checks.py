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


async def test_a_check_joined_to_two_answers_reads_the_newest_and_says_which(desk: Store) -> None:
    """Refusing to choose was the first answer here, and using it showed why that is wrong: an
    answer grown from a check arrives joined to that check, so two is the ordinary state after one
    "try again" — and the line to it is worked out rather than drawn, so it cannot be rubbed out.
    The fault the refusal was written for was reading one of several *silently*."""
    first = await _an_answer(desk, "one", "fine")
    second = await _an_answer(desk, "two", "also fine")
    made = await desk.add_check_card("no errors", "does not contain ERROR")

    answer = await routes.run_a_check(_a_form(id=made.id, on=f"answer:{first}%2Canswer:{second}"))

    assert json.loads(answer.body)["about"] == f"answer:{max(first, second)}"
    assert (await desk.check_card(made.id)).about == f"answer:{max(first, second)}"  # type: ignore[union-attr]


def test_the_card_says_which_one_it_reads_before_it_is_pressed() -> None:
    """A control that reaches for one of several has to say which, where somebody reads it rather
    than after they press."""
    assert "The newest of the ${joined} it is joined to." in _code()


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


# --- and what a failure does to the answer -------------------------------------------------------
def test_a_failed_answer_is_quarantined_rather_than_deleted() -> None:
    """ "Плохие ответы уезжают в отдельную обведённую область, а не удаляются." A wrong answer is
    what a right one is compared against, and deleting it throws away half of the working-out."""
    body = _body_of("quarantineFor")

    assert "classList.add('quarantined')" in body
    assert "remove()" in body, "nothing ever clears the frame"
    assert "'ring quarantine'" in body


def test_the_frame_says_what_is_wrong_and_not_only_that_something_is() -> None:
    """A grey card inside an outline says something is wrong. The sentence says what, and it is the
    sentence somebody acts on."""
    body = _body_of("quarantineFor")

    assert ".check-verdict" in body and "textContent" in body


def test_a_quarantined_card_is_still_readable() -> None:
    css = (HERE / "agent_desk" / "web" / "static" / "console.css").read_text(encoding="utf-8")

    assert ".pin.quarantined:hover, .pin.quarantined:focus-within { opacity: 1; }" in css
    assert ".pin.quarantined { opacity:" in css


def test_the_quarantine_is_worked_out_rather_than_remembered() -> None:
    """The verdict is on the check card and the line to the answer is on the bench. Working it out
    from those two is what makes it survive a reload without a second place to keep in step."""
    assert "quarantineFor(holder);" in _body_of("showCheck")


def test_a_check_that_passes_lets_the_answer_out() -> None:
    """Otherwise the first failure marks a card for ever, and nobody would use it twice."""
    body = _body_of("quarantineFor")
    start = body.index("if (!failed || !on.length)")

    assert "classList.remove('quarantined')" in body[:start], "clearing happens after the test"


# --- and a corrected answer growing out of it ----------------------------------------------------
def test_trying_again_carries_the_answer_that_failed_and_the_check() -> None:
    """ "Из карантина растут исправленные ответы." An attempt that cannot see what it failed is an
    attempt at the same answer, so both travel as cards the gesture named."""
    body = _body_of("tryAgain")

    assert "dataset.about" in body, "it redoes what it would read next, not what it judged"
    assert "made_from: [on[0], cardName(holder)].join(',')" in body
    assert "gesture: 'again'" in body


def test_trying_again_is_not_a_combine() -> None:
    """ "Answer it again, and this time satisfy the check" is the whole of the gesture, and there is
    nothing about it for anybody to configure — so it does not follow the bench's combining rule."""
    source = _code()

    assert "HOW_TO_TRY_AGAIN" in source
    assert "text: HOW_TO_TRY_AGAIN" in _body_of("tryAgain")
    route = (HERE / "agent_desk" / "web" / "routes.py").read_text(encoding="utf-8")
    assert 'if gesture == "combine" and len(combined) == 2:' in route


def test_it_is_offered_only_where_there_is_something_to_correct() -> None:
    """A "try again" on a check nobody has pressed asks the same question for no reason."""
    body = _body_of("showCheck")

    assert "again.hidden = !isCheck || !holder.querySelector('.check-verdict.failed');" in body


def test_a_gesture_is_named_rather_than_guessed_from_the_form() -> None:
    """The flag decides whether the classifier ever sees this text, and that is the branch that can
    start an agent. It should not hang on how many names a field happened to hold."""
    route = (HERE / "agent_desk" / "web" / "routes.py").read_text(encoding="utf-8")

    assert 'gesture = form.get("gesture", "").strip()' in route
    assert "a_gesture=bool(gesture)," in route


async def test_a_check_card_in_front_of_a_question_says_what_it_wants(desk: Store) -> None:
    """The digest describes it, condition and verdict both. Without that the next attempt is asked
    to do better with no idea what "better" meant."""
    from agent_desk.web import blocks

    made = await desk.add_check_card("no errors", "does not contain ERROR")
    await desk.card_checked(made.id, passed=False, why="it contains “ERROR”", judged=False)

    look = await blocks.on_the_bench(desk, [], [made.name], [made.name])

    (only,) = look.cards
    assert only.kind == "check"
    assert "does not contain ERROR" in only.said
    assert "it contains “ERROR”" in only.said, "the next attempt cannot see what it failed"


async def test_the_verdict_names_the_answer_it_is_about(desk: Store) -> None:
    """Found by using it: the corrected answer arrives joined to the check that asked for it, so
    "what did it judge" and "what will it read next" part company from that moment (063)."""
    block = await _an_answer(desk, "give me the log", "everything fine")
    made = await desk.add_check_card("no errors", "does not contain ERROR")

    await routes.run_a_check(_a_form(id=made.id, on=f"answer:{block}"))

    again = await desk.check_card(made.id)
    assert again is not None and again.about == f"answer:{block}"


async def test_editing_the_condition_forgets_what_it_judged(desk: Store) -> None:
    """A card that remembers what it judged while saying it has judged nothing is the pair of facts
    disagreeing."""
    made = await desk.add_check_card("a check", "is JSON")
    await desk.card_checked(made.id, passed=False, why="no", judged=False, about="answer:one")

    await desk.set_check_card(made.id, label="a check", said="shorter than 40")

    again = await desk.check_card(made.id)
    assert again is not None and again.about == ""


def test_a_check_does_not_read_what_it_has_already_set_aside() -> None:
    """Which is what leaves exactly one answer to press it on — the corrected one."""
    body = _body_of("whatItChecks")

    assert "name !== judged" in body


def test_the_frame_follows_the_verdict_and_not_the_lines() -> None:
    body = _body_of("quarantineFor")

    assert "dataset.about" in body
    assert "const on = about ? [about] : [];" in body


async def test_a_check_card_that_is_gone_describes_nothing(desk: Store) -> None:
    """A card can be named by a gesture and deleted before the run reads it. Describing it from
    nothing would be inventing a condition, which is the one thing a check must not do."""
    from agent_desk.web import blocks

    look = await blocks.on_the_bench(desk, [], ["check:01M1NOSUCH"], ["check:01M1NOSUCH"])

    assert look.cards == []
