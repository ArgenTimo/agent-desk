"""Hotkeys for a group of cards (01M1YWQJPCVDMD3BWAJZCM6GJ0).

"Идея — хоткеи для групп объектов."

The keys do what the bar's buttons do, by pressing them. A shortcut that drifts from the button
beside it is two behaviours wearing one name, and the one somebody learns is whichever they tried
first.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
BOARD = HERE / "agent_desk" / "web" / "templates" / "board.html"


def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def test_a_key_presses_the_button_rather_than_repeating_what_it_does() -> None:
    """Two implementations of "fold these" is two behaviours wearing one name."""
    source = _code()
    start = source.index("const GROUP_KEYS =")
    body = source[start : source.index("\n});", start)]

    assert 'bar.querySelector(`[data-many="${what}"]`)?.click();' in body
    for doing in ("classList.remove", "setView(", "pin.remove()"):
        assert doing not in body, f"the shortcut does {doing!r} itself"


def test_every_key_names_a_button_that_exists() -> None:
    """A shortcut for a control nobody drew is a key that does nothing and says nothing."""
    source = _code()
    start = source.index("const GROUP_KEYS =")
    line = source[start : source.index("\n", start + 20)]
    markup = BOARD.read_text(encoding="utf-8")

    for what in ("fold", "out", "off", "none"):
        assert f"'{what}'" in line
        assert f'data-many="{what}"' in markup


def test_the_keys_are_said_where_the_buttons_are() -> None:
    """A shortcut nobody can find is a shortcut for the person who wrote it."""
    markup = BOARD.read_text(encoding="utf-8")

    for key in ("(F)", "(I)", "(Delete)", "(Escape)"):
        assert key in markup


def test_they_do_nothing_while_there_is_no_group() -> None:
    """Delete over a bench with nothing chosen is a key that does nothing on Tuesday and empties
    the surface on Wednesday."""
    source = _code()
    start = source.index("const GROUP_KEYS =")
    body = source[start : source.index("\n});", start)]

    assert "if (!bar || bar.hidden) return;" in body


def test_choosing_everything_is_the_one_that_has_no_button() -> None:
    """The bar only appears once two cards are chosen, so there is nowhere to put "choose them
    all"."""
    source = _code()
    start = source.index("const GROUP_KEYS =")
    body = source[start : source.index("\n});", start)]

    assert "event.key.toLowerCase() === 'a' && (event.ctrlKey || event.metaKey)" in body
    assert "classList.add('chosen')" in body


def test_no_key_is_taken_from_the_tool_strip() -> None:
    """`x` is Combine and `g` is the area tool. A key that means two things is a key that means
    neither."""
    source = _code()
    keys = source[source.index("const GROUP_KEYS =") :]
    keys = keys[: keys.index("\n")]
    tools = source[source.index("const TOOL_KEYS = {") :]
    tools = tools[: tools.index("};")]

    for letter in ("v", "c", "g", "x"):
        assert f"{letter}: '" not in keys, f"{letter} is a tool key"
        assert f"{letter}: '" in tools


def test_a_field_being_typed_in_is_left_alone() -> None:
    source = _code()
    start = source.index("const GROUP_KEYS =")
    body = source[start : source.index("\n});", start)]

    assert "input, textarea, select, [contenteditable]" in body
