"""The button at the end of an enquiry (01M1XA1VATWR9CE7PERPEPGHE9).

"В финале я должен получить блок, в котором будет кнопка «добавить как идею» — при нажатии
собираем контекст из полученных карточек и формируем идею, помеченную как обычную, то есть мою."

The route that makes the idea was written when this set was started and is covered by
`test_author.py`. Nothing on the page ever called it: an idea could be made out of a bench only by
somebody who knew the URL, which is not a button. This is the button.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
BOARD = HERE / "agent_desk" / "web" / "templates" / "board.html"
ROUTES = HERE / "agent_desk" / "web" / "routes.py"


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


def test_there_is_a_button_and_it_is_wired_to_something() -> None:
    assert 'id="as-an-idea"' in BOARD.read_text(encoding="utf-8")
    assert "document.getElementById('as-an-idea')?.addEventListener('click'" in _code()


def test_it_appears_once_the_chat_has_said_what_it_is_about() -> None:
    """An enquiry is under way exactly when there is a beginning, and "keep what this came to" is
    a question that only makes sense then. On an ordinary bench it is a control with no meaning."""
    assert "asIdea.hidden = !surface?.querySelector('.pin.beginning')" in _body("syncTargets")


def test_it_calls_the_route_that_was_already_here() -> None:
    """One way of making an idea out of a bench. A second would be a second answer to what a card
    contributes, and they would disagree the first time one of them was improved."""
    assert "fetch('/ideas/from-bench'" in _body("keepThisAsAnIdea")
    assert ROUTES.read_text(encoding="utf-8").count('@router.post("/ideas/from-bench"') == 1


def test_it_sends_every_card_on_the_bench() -> None:
    """The answers, the cards they were about and whatever was dropped in are all how this was
    arrived at. Sending only what is charged for the next message would drop half the reasoning
    without saying so."""
    sending = _body("keepThisAsAnIdea")
    assert "onBench('.pin[data-kind]:not(.own)')" in sending


def test_it_asks_for_the_line_rather_than_writing_one() -> None:
    """The summary is what the card shows in a pool of two hundred, and after a conversation
    somebody has just driven, the one sentence they would use for it is a thing they have and the
    console does not."""
    sending = _body("keepThisAsAnIdea")
    assert "prompt('What did this come to? One line.'" in sending
    assert "if (!summary) return;" in sending


def test_it_says_what_happened_either_way() -> None:
    """A press that quietly does nothing is the one outcome a control like this cannot have."""
    sending = _body("keepThisAsAnIdea")
    assert "Written down as yours" in sending
    assert "said.why || 'Could not write it down.'" in sending
