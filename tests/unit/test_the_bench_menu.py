"""What a workbench can be asked for, and whether anybody can reach it.

Found by opening the console in a browser: `showBackgroundMenu` rebuilt `#bench-menu` with
`replaceChildren`, and the first right-click anybody made deleted every item authored in
`board.html`. Ten controls were served, hidden, and gone — "Add a step", "Add a button…",
"Add a check…", "Save this as a process…", "As a diagram…", "As it was…", "Save this workbench…"
and the two lists of saved things.

From the source every one of them looked wired: the markup was there, the handler was there, the
route was there, and the tests passed. Nothing but a browser could show it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
BOARD = (HERE / "agent_desk" / "web" / "templates" / "board.html").read_text(encoding="utf-8")
CONSOLE = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")


def _code() -> str:
    return "\n".join(line for line in CONSOLE.splitlines() if not line.lstrip().startswith("//"))


def _menu(which: str) -> str:
    """The markup of one menu, as authored."""
    said = BOARD[BOARD.index(f'<menu id="{which}"') :]
    return said[: said.index("</menu>")]


def test_the_two_menus_have_two_elements() -> None:
    """One element meant building the card's menu destroyed the bench's."""
    assert '<menu id="bench-menu"' in BOARD
    assert '<menu id="card-menu"' in BOARD


def test_a_card_s_menu_is_built_into_its_own_element() -> None:
    body = _code()[_code().index("function showCardMenu(") :]
    body = body[: body.index("\n}\n")]

    assert "cardMenu.replaceChildren()" in body
    assert "benchMenu" not in body


def test_the_bench_s_menu_is_the_one_that_was_written_down() -> None:
    """A list of what a workbench can be asked for belongs where the rest of the page is written,
    and a second copy of it in the script is the copy that wins and loses items."""
    body = _code()[_code().index("function showBackgroundMenu(") :]
    body = body[: body.index("\n}\n")]

    assert "replaceChildren" not in body
    assert "BACKGROUND_MENU" not in _code()


def test_every_control_the_bench_menu_offers_is_one_the_script_acts_on() -> None:
    """The other half of the same rule: an item authored with a word nothing dispatches on is an
    item that opens and does nothing."""
    offered = set(re.findall(r'data-add="([a-z]+)"', _menu("bench-menu")))
    acted = set(re.findall(r"what === '([a-z]+)'", _code()))

    assert offered - acted == set(), f"offered and never acted on: {sorted(offered - acted)}"


def test_the_ones_that_went_missing_are_back() -> None:
    """Named rather than counted, because each was a feature somebody built and nobody could
    reach."""
    said = _menu("bench-menu")

    for one in ("step", "button", "check", "template", "diagram", "rewind", "keep", "open"):
        assert f'data-add="{one}"' in said, one


def test_the_saved_lists_are_in_the_menu_that_survives() -> None:
    """`showMenu` fills them every time it opens, and they were being filled into an element whose
    children had just been thrown away."""
    said = _menu("bench-menu")

    assert 'id="bench-shelf"' in said
    assert 'id="bench-templates"' in said


def test_a_tall_menu_can_be_reached_all_the_way_down() -> None:
    """Twenty items is taller than a short window, and clamping where it opens is half an answer."""
    css = (HERE / "agent_desk" / "web" / "static" / "console.css").read_text(encoding="utf-8")
    rule = css[css.index(".bench-menu {") :]
    rule = rule[: rule.index("}")]

    assert "max-height" in rule
    assert "overflow-y: auto" in rule


def test_it_is_not_opened_above_the_top_of_the_window_either() -> None:
    body = _code()[_code().index("function showMenu(") :]
    body = body[: body.index("\n}\n")]

    assert "Math.max(8" in body


def test_clicking_away_closes_whichever_one_is_open() -> None:
    assert "closest('#bench-menu, #card-menu')" in _code()


def test_the_menu_is_measured_after_its_lists_have_arrived() -> None:
    """Two of the three lists fetch. Measuring before they answered measured a menu missing its two
    longest lists, and the clamp that keeps it inside the window was computed against a height it
    grew past a moment later — it opened at the pointer and ran off the bottom of the screen.

    Seen in the browser and nowhere else: from the source the clamp looks right, and it is right
    about the number it was given."""
    body = _code()[_code().index("async function showMenu(") :]
    body = body[: body.index("\n}\n")]

    assert "await Promise.all([showTemplates(), showShelf()])" in body
    assert body.index("await Promise.all") < body.index("offsetHeight")


# --- and the panel four things open ----------------------------------------------------------
def test_the_panel_can_be_closed_however_it_was_opened() -> None:
    """The dry run, the diagram, a saved workbench and the slider all open it and each writes its
    own title. Its only way out was the chip labelled "as if", which is the name of one of the four
    — somebody who opened it from the menu had a panel over a third of the workbench and nothing on
    it saying how to put it away."""
    said = BOARD[BOARD.index('<aside id="asif-panel"') :]
    said = said[: said.index("</aside>")]

    assert "data-asif-off" in said
    assert "[data-asif-off]" in _code()


def test_writing_the_title_does_not_take_the_way_out_with_it() -> None:
    """`header.textContent = …` would delete the button inside it, which is why the title is its
    own element."""
    assert 'class="asif-title"' in BOARD
    assert "querySelector('header').textContent" not in _code()
    assert _code().count("querySelector('.asif-title').textContent") == 3
