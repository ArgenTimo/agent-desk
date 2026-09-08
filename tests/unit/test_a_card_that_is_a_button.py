"""A card that holds a request and sends it when pressed (01M21HGXQ4K5TYK1VJKK7N684S).

"Карточка-кнопка с тонкими настройками. По умолчанию при нажатии просто отправляет указанный в ней
запрос, как будто бы мы его вписали в поле ввода, только без создания карточки запроса… Если кнопка
ни к чему не подключена связью — она работает со всем, что выделено; если подключена к чему-то —
работает с тем, с чем подключена."

The second sentence is what makes it more than a shortcut. A line on this bench has always been a
statement about two cards; from a button it is scope — the first time the drawing *does* something
rather than describing something.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import process, roles
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
BOARD = HERE / "agent_desk" / "web" / "templates" / "board.html"
BLOCKS = HERE / "agent_desk" / "web" / "templates" / "_blocks.html"


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


def _body(name: str) -> str:
    source = _code()
    start = source.index(f"function {name}(")
    return source[start : source.index("\n}\n", start)]


# --- the card ---------------------------------------------------------------------------------------
async def test_a_button_keeps_its_name_and_its_request(desk: Store) -> None:
    made = await desk.add_button_card("combine", "скомбинируй выбранные идеи")

    back = await desk.button_card(made.id)
    assert back is not None
    assert (back.label, back.prompt) == ("combine", "скомбинируй выбранные идеи")
    assert back.name == f"button:{made.id}"


async def test_both_are_edited_at_once(desk: Store) -> None:
    """A button renamed while its request still says something else is how a bench fills with
    controls nobody dares press."""
    made = await desk.add_button_card("combine", "combine them")

    await desk.set_button_card(made.id, label="decompose", prompt="break this into parts")

    back = await desk.button_card(made.id)
    assert back is not None and (back.label, back.prompt) == ("decompose", "break this into parts")


async def test_the_card_shows_the_request_it_will_send(desk: Store) -> None:
    """A button whose request you cannot read is a button you press once."""
    made = await desk.add_button_card("combine", "скомбинируй выбранные идеи")

    body = bytes((await routes.card("button", made.id)).body).decode()

    assert "скомбинируй выбранные идеи" in body
    assert 'action="/cards/button/edit"' in body


async def test_a_button_that_has_gone_says_so(desk: Store) -> None:
    answer = await routes.card("button", "01ZZZZZZZZZZZZZZZZZZZZZZZZ")

    assert answer.status_code == 404
    assert "not here any more" in bytes(answer.body).decode()


def test_a_button_is_not_a_step_and_will_never_be_run() -> None:
    """The run engine executes steps. A button is a thing on the surface that a person presses, and
    giving it a role out of the five is how the engine would come to try to run it."""
    assert "button" not in roles.NATURALLY
    assert roles.role_of("button").name not in process.STEPS


# --- what it reaches ---------------------------------------------------------------------------------
def test_joined_to_nothing_it_asks_about_what_is_chosen() -> None:
    reaching = _body("reaches")

    assert "if (joined.length) return" in reaching
    assert "return null;" in reaching, "there is no fallback to the ordinary context"


def test_joined_to_cards_it_asks_about_those() -> None:
    """However the selection stands. That is the whole of the rule, and it is what turns a line
    into scope."""
    reaching = _body("reaches")

    assert "everyTie()" in reaching
    assert "line.from === name ? [line.to] : line.to === name ? [line.from]" in reaching


def test_a_line_to_a_card_that_is_not_here_reaches_nothing() -> None:
    reaching = _body("reaches")

    assert '.pin[data-name="${CSS.escape(other)}"]' in reaching


def test_the_same_card_joined_twice_is_one_card() -> None:
    assert "new Set(joined)" in _body("reaches")


def test_it_says_what_it_will_reach_before_it_is_pressed() -> None:
    """A control that reaches for something different depending on the state of the bench has to
    say which."""
    saying = _body("saysWhatItReaches")

    assert "Joined to nothing" in saying
    assert "Joined to ${joined.length}" in saying


# --- pressing it --------------------------------------------------------------------------------------
def test_pressing_sends_what_the_card_asks() -> None:
    pressing = _body("pressTheButton")

    assert "fetch('/blocks'" in pressing
    assert "text: asks" in pressing


def test_a_button_with_nothing_written_on_it_sends_nothing() -> None:
    pressing = _body("pressTheButton")

    assert "if (!asks)" in pressing
    assert "nothing to ask yet" in pressing


def test_the_question_gets_no_card_of_its_own() -> None:
    """ "Как будто бы мы его вписали в поле ввода, только без создания карточки запроса." The
    conversation shows the question like any other message; the bench shows what came back."""
    source = _code()

    assert "button: 'yes'" in source
    assert "data-by-button" in BLOCKS.read_text(encoding="utf-8")
    assert "if (article.hasAttribute('data-by-button')) {" in _body("syncBlocks")


def test_what_came_back_still_becomes_a_card() -> None:
    """Which is the thing that was wanted: "появляется новый блок со скомбинированной идеей"."""
    syncing = _body("syncBlocks")
    where = syncing.index("data-by-button")

    assert "answerCard(article," in syncing[where : where + 400]


def test_an_answer_with_no_question_card_is_joined_to_nothing() -> None:
    """A line to a card that is not there explains nothing."""
    making = _body("answerCard")

    assert "if (asked) ownTies.push(" in making


async def test_the_block_records_that_a_button_sent_it(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="combine them", thread_set_by="human"
    )

    await desk.sent_by_a_button(block.id)

    again = await desk.block(block.id)
    assert again is not None and again.by_button is True


async def test_an_ordinary_message_is_not_marked(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="hello", thread_set_by="human"
    )

    again = await desk.block(block.id)
    assert again is not None and again.by_button is False


# --- and how one is made --------------------------------------------------------------------------------
def test_there_is_a_way_to_make_one() -> None:
    assert 'data-add="button"' in BOARD.read_text(encoding="utf-8")
    assert "function addButton(" in _code()


def test_what_it_reaches_is_said_again_whenever_the_lines_change() -> None:
    """Said once when the card arrived, it went on claiming "joined to nothing" after somebody
    joined it to something — a control describing a scope it no longer has. Found in the browser:
    drawing a line to the button left its own sentence stale."""
    drawing = _body("drawTies")

    assert "saysWhatItReaches(one)" in drawing
