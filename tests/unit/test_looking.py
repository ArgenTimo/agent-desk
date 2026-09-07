"""What the model is shown when it is asked about the workbench.

A question used to carry a list of names. `idea:01M1XC4YZHPE076JTH5BCXMD9W` says that an idea is on
the bench and nothing else, so "highlight the ones that could make money" could not be answered
from the bench at all — only from the wording of the question, which is the same answer with none
of the evidence.

These are about the three things the digest has to be at once, and each of them is a way it can be
wrong quietly: complete (an answer about eleven of fourteen cards looks exactly like an answer
about fourteen), compact (a bench is sent on every question asked with cards in front of it), and
numbered (a card the model cannot name is a card it cannot act on).
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import looking

REPO = pathlib.Path(__file__).resolve().parents[2]


def _cards(how_many: int) -> list[looking.OnBench]:
    return [
        looking.OnBench(name=f"idea:{n}", kind="idea", label=f"card {n}", said=f"about {n}")
        for n in range(how_many)
    ]


# --- numbered, so a card can be named -------------------------------------------------------------
@pytest.mark.unit
def test_every_card_has_a_number_and_no_two_share_one() -> None:
    """The whole point of numbering: a card the model names is one card and not two."""
    look = looking.look(_cards(5), [])

    assert [card.at for card in look.cards] == [1, 2, 3, 4, 5]
    assert len({card.at for card in look.cards}) == 5


@pytest.mark.unit
def test_a_number_leads_back_to_exactly_one_card() -> None:
    """A number is only useful if the console can turn it back into the card it stood for."""
    look = looking.look(_cards(3), [])

    assert {card.at: card.name for card in look.cards} == {
        1: "idea:0",
        2: "idea:1",
        3: "idea:2",
    }


@pytest.mark.unit
def test_the_rendered_digest_tells_the_model_to_answer_in_numbers() -> None:
    """An instruction that only holds when the section is present lives with the section.

    Told in the prompt builder instead, it would arrive on questions asked with an empty bench —
    an instruction to answer in numbers with no numbered list, which is an instruction to invent
    some.
    """
    said = "\n".join(looking.as_lines(looking.look(_cards(2), [])))

    assert "by number" in said
    assert looking.as_lines(looking.look([], [])) == []


# --- complete -------------------------------------------------------------------------------------
@pytest.mark.unit
def test_what_a_card_is_and_what_is_written_on_it_both_travel() -> None:
    card = looking.OnBench(
        name="session:abc",
        kind="session",
        label="llm-developer-1",
        said="rewriting the registry reader",
        role="action",
    )

    said = "\n".join(looking.as_lines(looking.look([card], [])))

    assert "session" in said
    assert "llm-developer-1" in said
    assert "rewriting the registry reader" in said
    assert "action" in said, "the role a card has in a process is part of what it is"


@pytest.mark.unit
def test_the_lines_between_cards_travel_as_numbers() -> None:
    """A relation stated in ULIDs is a relation the model has to match up by eye."""
    look = looking.look(_cards(3), [("idea:0", "idea:2", "makes")])

    assert look.joins == [looking.Joined(frm=1, to=3, says="makes")]
    assert "1 makes 3" in "\n".join(looking.as_lines(look))


@pytest.mark.unit
def test_a_line_with_one_end_off_the_bench_is_not_drawn_to_nothing() -> None:
    """The same rule the workbench diagram follows: a relation to something the reader cannot see
    explains nothing, and naming a number that is not in the list invites an answer about it."""
    look = looking.look(_cards(2), [("idea:0", "idea:somewhere-else", "then")])

    assert look.joins == []


@pytest.mark.unit
def test_cards_that_did_not_fit_are_counted_out_loud() -> None:
    """The failure this exists to stop: an answer about "everything on the bench" given eleven of
    fourteen cards is wrong in a way nobody can see from reading the answer.

    A guessed completeness is the guessed status of CLAUDE.md's fifth rule wearing a list.
    """
    look = looking.look(_cards(looking.MOST_CARDS + 7), [])

    assert len(look.cards) == looking.MOST_CARDS
    assert look.left_out == 7
    assert "7 more cards" in "\n".join(looking.as_lines(look))


@pytest.mark.unit
def test_a_bench_that_fits_says_nothing_about_what_did_not() -> None:
    """A count of zero rendered as a sentence would be a warning about nothing, on every question."""
    said = "\n".join(looking.as_lines(looking.look(_cards(3), [])))

    assert "more cards" not in said


# --- compact --------------------------------------------------------------------------------------
@pytest.mark.unit
def test_one_card_is_one_line_however_many_newlines_are_in_it() -> None:
    """An idea's text is a paragraph. Rendered as it is written, one card would take twenty lines
    of a digest whose whole shape is one line per card."""
    card = looking.OnBench(name="idea:a", kind="idea", label="a thought", said="one\n\ntwo\n three")

    (only,) = [one for one in looking.look([card], []).cards]

    assert only.said == "one two three"


@pytest.mark.unit
def test_a_long_card_is_trimmed_and_says_it_was() -> None:
    card = looking.OnBench(name="idea:a", kind="idea", label="a thought", said="x" * 400)

    (only,) = looking.look([card], []).cards

    assert len(only.said) == looking.SAID_CHARS
    assert only.said.endswith("…"), "a trimmed sentence that does not say so reads as a whole one"


@pytest.mark.unit
def test_a_card_with_nothing_written_on_it_invents_nothing() -> None:
    """ "Nobody has looked at this yet" is a real state and has to look like one."""
    card = looking.OnBench(name="folder:/tmp/x", kind="folder", label="x")

    said = "\n".join(looking.as_lines(looking.look([card], [])))

    assert said.count("x") >= 1
    assert (only := looking.look([card], []).cards[0]).said == ""
    assert only.label == "x"


@pytest.mark.unit
def test_a_card_does_not_say_its_own_label_twice() -> None:
    """A step card's label *is* what is written on it, and printing it as both is a line of noise
    on every card of the commonest kind."""
    card = looking.OnBench(
        name="step:a", kind="step", label="check the logs", said="check the logs"
    )

    said = "\n".join(looking.as_lines(looking.look([card], [])))

    assert said.count("check the logs") == 1


@pytest.mark.unit
def test_a_card_with_no_label_at_all_is_still_findable() -> None:
    """Its name is a worse label than a summary and a better one than an empty line — a card
    rendered as `4. idea — ` cannot be told apart from the one under it."""
    card = looking.OnBench(name="idea:01M1X", kind="idea", label="")

    assert looking.look([card], []).cards[0].label == "idea:01M1X"


# --- and it is actually given to the model --------------------------------------------------------
@pytest.mark.unit
def test_the_workbench_reaches_the_prompt() -> None:
    """A digest nothing sends is a digest that describes nothing."""
    from agent_desk.answer.session import build_prompt

    prompt = build_prompt(
        "which of these could make money",
        board=["a session"],
        history=[],
        workbench=looking.as_lines(looking.look(_cards(2), [])),
    )

    assert "## The workbench" in prompt
    assert "1. idea — card 0" in prompt


@pytest.mark.unit
def test_an_empty_bench_adds_no_heading() -> None:
    """Every question that is not about the bench would otherwise carry a heading with nothing
    under it, and a heading with nothing under it is a thing to explain."""
    from agent_desk.answer.session import build_prompt

    prompt = build_prompt("how is it going", board=["a session"], history=[])

    assert "## The workbench" not in prompt


@pytest.mark.unit
def test_the_bench_is_described_before_the_thread_and_the_transcripts() -> None:
    """A question asked with cards in front of it is usually a question about those cards, and
    the thing it is about should not be reached by scrolling past everything it is not."""
    from agent_desk.answer.session import build_prompt

    prompt = build_prompt(
        "which of these",
        board=["a session"],
        history=[("earlier", "an answer")],
        transcripts=["### a session", "assistant: something"],
        workbench=looking.as_lines(looking.look(_cards(1), [])),
    )

    assert prompt.index("## The workbench") < prompt.index("## Earlier in this thread")
    assert prompt.index("## The workbench") < prompt.index("## The transcripts")


@pytest.mark.unit
def test_the_digest_reads_no_store_and_no_clock() -> None:
    """Pure, so that what the model is shown can be checked without a database and a board.

    Asserted against the imports rather than against a habit: this module is the one place the
    bench is turned into words, and the day it starts reading rows is the day it can only be
    tested by arranging a session on disk.
    """
    import ast

    tree = ast.parse((REPO / "agent_desk" / "looking.py").read_text(encoding="utf-8"))
    imported = {
        name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}

    assert not {one for one in imported if one.startswith("agent_desk.store")}
    assert "time" not in imported and "datetime" not in imported


# --- gathering it: which of several sources says what a card is -----------------------------------
@pytest.fixture
async def desk(tmp_path: pathlib.Path):  # type: ignore[no-untyped-def]
    from agent_desk.store.repo import Store

    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


@pytest.mark.unit
async def test_an_idea_is_shown_in_its_own_words(desk) -> None:  # type: ignore[no-untyped-def]
    """Most specific first, and a person's own words are the most specific there is.

    A sentence a background pass wrote about an idea is a paraphrase of a thing the person already
    said in full. Showing the paraphrase would be this console reading the idea back to itself.
    """
    from agent_desk.web import blocks

    idea = await desk.create_idea(
        text_="the registry should be read before the transcript",
        summary="read the registry first",
        source_kind="typed",
        source_ref=None,
        context=None,
    )
    await desk.say_card(f"idea:{idea.id}", "a paraphrase nobody asked for", "")

    look = await blocks.on_the_bench(desk, [], [f"idea:{idea.id}"])

    (only,) = look.cards
    assert only.label == "read the registry first"
    assert only.said == "the registry should be read before the transcript"


@pytest.mark.unit
async def test_a_session_falls_back_from_a_description_to_its_own_headline(desk) -> None:  # type: ignore[no-untyped-def]
    """Descriptions are written lazily, four at a time, so most cards have none for a while.

    The fallback matters more than the description: a card that says nothing until a background
    pass gets to it is a card the model cannot reason about, on exactly the questions asked
    soonest after dropping it.
    """
    from agent_desk.web import blocks

    from tests.unit.test_input import make_row

    row = make_row("duck", "main")

    look = await blocks.on_the_bench(desk, [row], [f"session:{row.session.session_id}"])

    (only,) = look.cards
    assert only.said == "a title", "the session's own headline was not used"

    await desk.say_card(f"session:{row.session.session_id}", "rewriting the registry reader", "")
    look = await blocks.on_the_bench(desk, [row], [f"session:{row.session.session_id}"])

    assert look.cards[0].said == "rewriting the registry reader", "the description did not win"


@pytest.mark.unit
async def test_the_conversation_is_not_a_card_on_the_bench(desk) -> None:  # type: ignore[no-untyped-def]
    """A block card is the question and its answer. Both are already in the prompt as the thread,
    and listing them again would have the model reason about the conversation as a thing it can be
    asked to move."""
    from agent_desk.web import blocks

    look = await blocks.on_the_bench(desk, [], ["block:01M1X", "folder:/tmp/x"])

    assert [card.kind for card in look.cards] == ["folder"]


@pytest.mark.unit
async def test_the_same_card_twice_is_one_card(desk) -> None:  # type: ignore[no-untyped-def]
    """A card asked for in full arrives as `kind:id:full` beside its own plain name, and two
    numbers for one card is two things for the model to pick between when there is one."""
    from agent_desk.web import blocks

    look = await blocks.on_the_bench(desk, [], ["folder:/tmp/x", "folder:/tmp/x:full"])

    assert len(look.cards) == 1


@pytest.mark.unit
async def test_a_line_drawn_between_two_cards_on_the_bench_is_shown(desk) -> None:  # type: ignore[no-untyped-def]
    from agent_desk.web import blocks

    await desk.tie_cards(
        from_name="folder:/tmp/a", to_name="folder:/tmp/b", kind="then", says="then"
    )

    look = await blocks.on_the_bench(desk, [], ["folder:/tmp/a", "folder:/tmp/b"])

    assert look.joins == [looking.Joined(frm=1, to=2, says="then")]
