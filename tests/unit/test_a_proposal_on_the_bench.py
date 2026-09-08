"""Drag a proposal onto the workbench and it becomes what the enquiry is about
(01M1XA1VANP65NTB5GHP3NRQ5X).

"Я перетягиваю твою идею на верстак, начинаю задавать тебе вопросы, уточнения и т.д., говорить, как
я это вижу (всё это в процессе визуализируется карточками)."

The idea itself says this is scenario 9 applied to an idea — one mechanism, not two — so nothing
here builds an enquiry. It says which card the enquiry starts from, and everything after that is
the workbench doing what it already does: a question is read as following on from a card, the line
is drawn, the answer is a card of its own, and the layout follows the lines.

The point of the whole set is underneath it: a proposal is an idea nobody holds the context of yet
(039-idea-author.sql), and the way to come to hold it is to ask about it.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)
IDEAS = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "templates" / "_ideas.html"
)


def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def _dropping() -> str:
    source = _code()
    start = source.index("document.addEventListener('drop'")
    return source[start : source.index("\n});\n", start)]


def test_a_dropped_proposal_becomes_what_the_chat_is_about() -> None:
    assert "beginFrom(`${kind}:${id}`)" in _dropping()


def test_only_a_proposal_does() -> None:
    """Every idea becoming the root of an enquiry would hijack an ordinary bench, where ideas are
    dropped in to be asked *about* rather than asked *into*."""
    assert "if (!unlooked || surface.querySelector('.pin.beginning')) return;" in _dropping()


def test_a_beginning_somebody_already_set_is_not_replaced() -> None:
    """The console overruling somebody about what they are working on."""
    assert "surface.querySelector('.pin.beginning')) return;" in _dropping()


def test_it_says_what_it_did() -> None:
    """A card that quietly became the root of everything asked afterwards is a state change nobody
    was told about, and the first sign of it is an answer that came back about the wrong thing."""
    assert "say('Asking about this one — what you ask next hangs off it.')" in _dropping()


def test_whether_it_was_a_proposal_is_read_before_the_drop_lands() -> None:
    """The column the card was dragged from is re-rendered by the drop's own consequences, so the
    element it was read from may not be there to ask afterwards."""
    source = _code()
    start = source.index("document.addEventListener('dragstart'", source.index("fromPins") - 3000)
    starting = source[start : source.index("\n});\n", start)]
    assert "unlooked: card.classList.contains('unlooked')" in starting


def test_the_class_it_reads_is_the_one_the_idea_column_writes() -> None:
    """A class name agreed on between a template and a script, asserted in both places, because a
    rename in one of them is a feature that silently stops happening."""
    assert "idea.proposed %} unlooked{%" in IDEAS.read_text(encoding="utf-8")


def test_it_waits_for_the_card_before_marking_it() -> None:
    """`beginFrom` marks the card on the surface, and the card is not on the surface until `pin`
    has finished putting it there."""
    dropping = _dropping()
    assert "pin(dragged, { came: 'dropped on the workbench' }).then(() =>" in dropping
