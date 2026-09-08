"""A question and its answer are two cards, not one entry in a feed (01M1XA1V712MDXBWXZG4VNJ4MJ).

"Сегодня вопрос и ответ — это один блок. Для исследования их надо разнять: к вопросу крепится
ответ, к ответу крепится следующий вопрос, и каждое из этого — точка ветвления. Один блок на пару
такой точкой быть не может."

The reason it matters is not tidiness. A branch point is a card somebody draws a line from, and
following up on what was asked and following up on what came back are two different questions. On
one card they are the same line out of the same box, and a research thread flattens back into the
feed it was supposed to stop being.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk.ideas import bench

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
BLOCKS = HERE / "agent_desk" / "web" / "blocks.py"


def _code() -> str:
    """The script without its comments. A test that reads the prose describing a rule cannot tell
    the rule from the paragraph explaining why it is there."""
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def _body(name: str) -> str:
    source = _code()
    start = source.index(f"function {name}(")
    return source[start : source.index("\n}\n", start)]


def test_what_was_asked_and_what_came_back_are_cut_apart() -> None:
    halving = _body("halfOf")
    assert "cloneNode(true)" in halving, "the article itself would be moved out of #blocks"
    assert "ASKED_PARTS" in halving
    assert "part.remove()" in halving


def test_the_question_half_is_a_list_and_the_answer_half_is_the_rest() -> None:
    """A part nobody thought about lands with the answer rather than vanishing. The other way
    round — list the answer's parts — loses a new one silently, which on this bench looks like an
    answer that never arrived."""
    asked = _code()[_code().index("const ASKED_PARTS") :].split("\n")[0]
    for part in (".said", ".taken-as", ".carried"):
        assert part in asked
    assert ".answer" not in asked, "the answer half is defined by exclusion, not by a second list"


def test_an_answer_card_is_made_only_once_there_is_something_on_it() -> None:
    """An empty card under every question is a bench of half-cards."""
    making = _body("answerCard")
    assert "if (!half.children.length) return null;" in making


def test_the_two_are_joined_by_a_line() -> None:
    making = _body("answerCard")
    assert "ownTies.push({ from: `block:${id}`, to: name, says: 'answered' })" in making


def test_the_answer_is_placed_under_its_question() -> None:
    assert "place(node, spotUnder([`block:${id}`]))" in _body("answerCard")


def test_what_an_answer_wrote_hangs_off_the_answer() -> None:
    """An idea written down by an answer, drawn under the question, reads as something somebody
    asked about — which is the opposite claim."""
    syncing = _body("syncBlocks")
    assert "`answer:${id}`\n      : `block:${id}`" in syncing
    assert syncing.count("{ under: from") == 2, "both the drawn cards and the ideas"


def test_a_card_can_be_hung_under_anything_that_has_a_name() -> None:
    """`under` used to take a block id and build `block:<id>` from it, which made a block the only
    thing on the bench a card could arrive beneath."""
    pinning = _body("pin")
    assert "spotUnder([how.under])" in pinning
    assert "ownTies.push({ from: how.under" in pinning
    assert "block:${how.under}" not in pinning


def test_both_halves_go_when_the_exchange_does() -> None:
    """They are cleared by the block's own name: an answer card left behind by a thread switch is
    an answer floating over another chat's bench."""
    syncing = _body("syncBlocks")
    assert ".pin.block-card, .pin.answer-card" in syncing
    assert "wanted.has(`block:${node.dataset.id}`)" in syncing


def test_a_restored_answer_keeps_its_place_and_is_not_drawn_twice() -> None:
    """It is redrawn from #blocks like the question; laying it out again would put a second copy
    of the exchange on the bench on every reload."""
    laying = _body("layOut")
    assert "one.kind === 'block' || one.kind === 'answer'" in laying


def test_an_answer_is_not_counted_as_a_card_the_next_message_carries() -> None:
    """`on_the_bench` drops it from the prompt, so counting it would say the message carries twice
    what it carries."""
    assert ":not(.answer-card)" in _body("syncTargets")
    assert ":not(.answer-card)" in _body("pinnedTargets")


def test_the_prompt_leaves_both_halves_out() -> None:
    source = BLOCKS.read_text(encoding="utf-8")
    assert 'if kind in ("block", "answer")' in source


def test_the_answer_has_a_column_of_its_own_beside_the_question() -> None:
    assert bench.COLUMN["answer"] == bench.COLUMN["block"] + 1
    assert bench.COLUMN["idea"] > bench.COLUMN["answer"], "an idea comes out of an answer"
