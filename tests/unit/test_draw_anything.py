"""Draw whatever is in front of you, not only a process (01M1X8DA5F5KA6KTPP1C7BJNQC).

"Попросить создать ЛЮБЫЕ блоки на экране, например визуализировать что угодно, например как у нас
устроена БД, или как работают микросервисы."

Two things were missing and they are different. Five process words draw a process and are useless
for anything else — a table is not an Action and a foreign key is not a `then` — so there had to be
a second vocabulary. And a model asked to draw "our database" will draw a plausible one from
memory, which is not a wrong summary of something true but a picture of something that does not
exist.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import telling, ties

pytestmark = pytest.mark.unit

BLOCKS = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "blocks.py"


# --- the second vocabulary -------------------------------------------------------------------------
def test_a_relation_is_read_with_its_own_name_on_it() -> None:
    _, lines = telling.read_shape(
        "object | orders | the orders table\nobject | users | the users table\n1 -> 2 : foreign key"
    )

    assert lines == [{"from": "1", "to": "2", "kind": "named", "says": "foreign key"}]


def test_a_relation_of_several_words_keeps_all_of_them() -> None:
    """ "Deploys to" is the name of the relation. Reading the first word of it and dropping the rest
    is how a diagram comes back saying "deploys"."""
    _, lines = telling.read_shape("object | a | a\nobject | b | b\n1 -> 2 : is deployed onto")

    assert lines[0]["says"] == "is deployed onto"


def test_the_kind_stays_one_of_a_closed_set() -> None:
    """A line whose *kind* is free text is a note with an arrow on it: nothing can reason about it,
    `natural` cannot suggest it, `odd_pair` cannot question it, and the route that draws lines
    would have to accept any string anybody sent."""
    _, lines = telling.read_shape("object | a | a\nobject | b | b\n1 -> 2 : foreign key")

    assert ties.is_a_kind(lines[0]["kind"])


def test_a_named_line_with_nothing_on_it_says_nothing() -> None:
    """Which is why it asks for words, the way a branch does."""
    assert ties.KINDS["named"].wants_words


def test_a_line_pointing_at_a_card_that_is_not_there_is_still_dropped() -> None:
    """The rule the process lines already had. A drawing with a dangling arrow is harder to correct
    than one with none, whichever vocabulary drew it."""
    _, lines = telling.read_shape("object | a | a\n1 -> 9 : foreign key")

    assert lines == []


def test_the_prompt_offers_both_and_says_when_each_is_for() -> None:
    asked = telling.shape_prompt("how our database is put together")

    assert "For a process" in asked
    assert "For anything else" in asked
    assert "foreign key" in asked


# --- and not from memory ----------------------------------------------------------------------------
def test_the_prompt_forbids_drawing_from_memory() -> None:
    """ "Схема, нарисованная по памяти, выглядит правдоподобно и является выдумкой." Nothing
    downstream can tell a drawing of a real schema from a drawing of a plausible one, so the only
    place the distinction can be made is where the drawing is not made."""
    asked = telling.shape_prompt("how our database is put together")

    assert "Never draw from memory" in asked
    assert "cannot: <what you would need to be shown>" in asked


def test_what_is_on_the_bench_is_what_can_be_seen() -> None:
    asked = telling.shape_prompt("draw this", ["- schema.sql: the tables and their keys"])

    assert "## What you can see" in asked
    assert "- schema.sql: the tables and their keys" in asked


def test_an_empty_bench_adds_no_heading() -> None:
    """A heading with nothing under it reads as "you have been shown nothing, here it is"."""
    assert "What you can see" not in telling.shape_prompt("draw a release process")


def test_the_refusal_is_read_back_with_its_reason() -> None:
    assert telling.read_cannot("cannot: the schema — no file here describes it") == (
        "the schema — no file here describes it"
    )


def test_a_drawing_is_not_a_refusal() -> None:
    assert telling.read_cannot("object | a | a\n1 -> 2 : foreign key") == ""


def test_a_refusal_that_also_drew_something_is_taken_as_the_drawing() -> None:
    """A reply that says both drew from memory anyway, and the drawing is the part that would be
    put in front of somebody. Nothing here is trusted more than the fact that cards came back."""
    source = BLOCKS.read_text(encoding="utf-8")

    assert (
        "if (needed := telling.read_cannot(reply)) and not telling.read_shape(reply)[0]:" in source
    )


def test_the_refusal_says_what_to_do_about_it() -> None:
    source = BLOCKS.read_text(encoding="utf-8")

    assert "Put it on the " in source
    assert "workbench — a file, a folder, an answer that describes it — and ask again." in source


def test_the_bench_reaches_the_drawing() -> None:
    """It was drawing from the words in the field and nothing else, which is exactly the position
    from which a schema gets invented."""
    source = BLOCKS.read_text(encoding="utf-8")

    assert "await _draw_it(store, block, surface=surface)" in source
    assert "telling.shape_prompt(block.input, surface)" in source
