"""Everything the console can do, reachable from the keyboard (01M1XC4Z18MW…).

"Ctrl+K сегодня ищет карточки. Жестов стало столько, что нужен и второй режим: не «найди вещь», а
«сделай действие» — соединить, раскрыть, запустить, разложить, сохранить как процесс."

**One door, not a second shortcut.** The idea asks for a second mode; this is one palette that
holds both, and the assumption is stated because it is a reading rather than a given. Somebody who
has to remember which of two palettes holds the thing they want has been given a filing problem
instead of a keyboard: typing "undo" finds the action, typing "duck" finds the project, and the row
says which it is.

**The actions are read off the page.** A hand-written list of what the console can do is a list
that falls behind the day somebody adds a button — and this idea is exactly "everything the console
can do", so a list that can be incomplete answers the wrong question.
"""

from __future__ import annotations

import pathlib
import re

import pytest

WEB = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web"
CONSOLE = WEB / "static" / "console.js"
BOARD = WEB / "templates" / "board.html"


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


@pytest.mark.unit
def test_the_actions_are_gathered_from_the_controls_rather_than_listed() -> None:
    """So that a button added next week is in the palette on the same commit, without being
    mentioned twice and without either mention being the one that is wrong."""
    gathering = _body("everyAction")

    assert "ACTION_BARS" in gathering
    assert "querySelectorAll" in gathering
    assert "'.bench-head', '#bench-menu'" in _code(), (
        "the two places a control that acts on the workbench lives are no longer named"
    )


@pytest.mark.unit
def test_an_action_is_done_by_pressing_the_control_it_was_read_off() -> None:
    """One path. Calling the function behind the button instead would let the palette do a thing
    differently from the button for it, and only one of the two would be the tested one."""
    taking = _body("takePalette")

    assert "one.button.click()" in taking


@pytest.mark.unit
def test_the_palette_holds_both_and_puts_the_doing_first() -> None:
    """With nothing typed the question is "what can I do"; with something typed, a word that names
    an action almost always means the action — "undo" is not a card."""
    matching = _body("paletteMatches")

    assert "everyAction()" in matching and "everythingOnThePage()" in matching
    assert matching.index("everyAction()") < matching.index("everythingOnThePage()")
    assert "[...doing, ...things]" in matching


@pytest.mark.unit
def test_a_pointer_at_one_card_is_not_a_thing_the_console_can_do() -> None:
    """The dots for cards that are off the screen live in the bench head, and there can be thirty
    of them. Each is a way to reach one card, which is the card list the palette already has, under
    worse names — they filled it completely on a bench of thirty-five."""
    gathering = _body("everyAction")

    assert "closest('#off-edge')" in gathering


@pytest.mark.unit
def test_every_control_the_palette_offers_can_be_named() -> None:
    """A control whose words are a number cannot be asked for: the zoom button reads "65%" on a
    zoomed-out bench, and nobody types that. Every button in the two bars either has words that
    stay put or says its name out loud."""
    board = BOARD.read_text(encoding="utf-8")

    for bar in ("bench-head", "bench-menu"):
        block = board[board.index(bar) :]
        block = block[: block.index("</div>" if bar == "bench-head" else "</menu>")]
        for tag, inside in re.findall(r"(<button[^>]*>)(.*?)</button>", block, re.S):
            words = re.sub(r"\s+", " ", re.sub(r"\{[#{%].*?[#}%]\}", "", inside)).strip()
            if not words or not words.replace("%", "").strip().isdigit():
                continue
            assert "aria-label" in tag, (
                f"a control whose words are {words!r} cannot be asked for by name — that number "
                "changes with the zoom, so it needs an aria-label that does not"
            )

    assert 'aria-label="back to full size"' in board, (
        "the zoom control's words are a number that changes, so it needs a name that does not"
    )


@pytest.mark.unit
def test_the_field_says_it_does_things_as_well_as_finds_them() -> None:
    """A palette that offers actions behind a placeholder promising only things is a palette whose
    other half nobody discovers."""
    console = _code()

    assert "undo, lay it out again" in console
    assert "Enter does it, or puts it on the workbench" in console
