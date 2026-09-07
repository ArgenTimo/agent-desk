"""Where things go, asked for in words.

The reading is the whole of this module, and everything asserted here is one of two things: that
an arrangement comes back as columns with names on them, or that something which is not an
arrangement moves nothing at all. The second half is the more important one — a bench half
rearranged on a half-read reply looks exactly like an answer and is not one.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import placing

STATIC = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"
TEMPLATES = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "templates"


@pytest.mark.unit
def test_columns_come_back_in_the_order_they_were_answered_in() -> None:
    """ "Справа помести… а слева те…" Left to right is the answer's own order, which is why the
    prompt asks for it that way rather than asking for a side per column."""
    columns, left = placing.read_columns(
        "interesting to developers | 1, 3\ninteresting to everybody else | 2, 4\n", 4
    )

    assert [one.title for one in columns] == [
        "interesting to developers",
        "interesting to everybody else",
    ]
    assert [one.cards for one in columns] == [[1, 3], [2, 4]]
    assert left == []


@pytest.mark.unit
def test_a_column_with_no_heading_is_not_a_column() -> None:
    """Two piles nobody can name a minute later is a shuffle, not an arrangement — the heading is
    the entire difference, so a column without one is dropped rather than titled by us."""
    columns, left = placing.read_columns(" | 1, 2\nthe rest | 3", 3)

    assert [one.title for one in columns] == ["the rest"]
    assert left == [1, 2]


@pytest.mark.unit
def test_a_line_with_words_after_the_bar_is_thrown_away_unread() -> None:
    """The same strictness as `classify.read_related`, and for the same reason: mining digits out
    of "see 3 of the cards above" would arrange one card and look like an answer."""
    columns, _ = placing.read_columns("developers | see 3 of the cards above\nusers | 1, 2", 3)

    assert [one.title for one in columns] == ["users"]


@pytest.mark.unit
def test_a_reply_that_is_a_paragraph_about_an_arrangement_arranges_nothing() -> None:
    """A model asked to arrange things will sometimes describe the arrangement instead. Nothing
    parses, nothing moves, and the route says so — rather than a bench half rearranged."""
    columns, left = placing.read_columns(
        "I would put the developer-facing ideas on the right and the rest on the left.", 4
    )

    assert columns == []
    assert left == [1, 2, 3, 4]


@pytest.mark.unit
def test_a_card_belongs_to_the_first_column_that_claims_it() -> None:
    """A card is in one place on a bench. The alternative is the same card drawn twice, which is a
    picture of something that cannot happen."""
    columns, left = placing.read_columns("one | 1, 2\ntwo | 2, 3", 3)

    assert [one.cards for one in columns] == [[1, 2], [3]]
    assert left == []


@pytest.mark.unit
def test_a_number_that_names_no_card_is_dropped_rather_than_guessed_at() -> None:
    columns, left = placing.read_columns("one | 1, 9, 0\n", 3)

    assert [one.cards for one in columns] == [[1]]
    assert left == [2, 3]


@pytest.mark.unit
def test_the_cards_nobody_placed_come_back_named() -> None:
    """They are what the request said nothing about, and the page gives them a column of their
    own. Left where they were, they would end up underneath the new columns."""
    _, left = placing.read_columns("worth money | 2", 4)

    assert left == [1, 3, 4]


@pytest.mark.unit
def test_a_numbered_list_still_reads_as_columns() -> None:
    """A model answering in a list writes "1. developers | 1, 4". Only that marker comes off the
    front of a heading: stripping digits generally would turn "2026 plans" into "plans"."""
    columns, _ = placing.read_columns("1. developers | 1\n2) users | 2\n2026 plans | 3", 3)

    assert [one.title for one in columns] == ["developers", "users", "2026 plans"]


@pytest.mark.unit
def test_a_heading_is_a_few_words_and_not_a_paragraph() -> None:
    """It is read at a glance over a column of cards, and a column 260 pixels wide cannot show
    more than a few words of it however long the model made it."""
    (column,) = placing.read_columns("x" * 400 + " | 1", 1)[0]

    assert len(column.title) == placing.MOST_TITLE


@pytest.mark.unit
def test_the_prompt_names_every_card_and_what_was_asked() -> None:
    asked = placing.columns_prompt(
        "справа те что интересны разработчикам",
        ["idea — a parser — reads the registry", "session — biba — running the tests"],
    )

    assert "1. idea — a parser — reads the registry" in asked
    assert "2. session — biba — running the tests" in asked
    assert "справа те что интересны разработчикам" in asked


@pytest.mark.unit
def test_the_prompt_forbids_inventing_a_card_and_allows_leaving_one_out() -> None:
    """The counterpart of `telling.shape_prompt`'s rule against inventing steps. A model told to
    place everything will file a session card under "interesting to ordinary users" rather than
    admit the request said nothing about it, and one confident lie in an arrangement is worse than
    a short last column."""
    asked = " ".join(placing.columns_prompt("sort them", ["idea — one"]).split())

    assert "at most one column" in asked
    assert "goes in no column at all" in asked
    assert "never invent a card that is not in the list" in asked


@pytest.mark.unit
def test_the_page_applies_an_arrangement_and_keeps_the_way_back() -> None:
    """This is the branch where guessing is allowed, and the reason is that it is cheap: nothing
    is created, nothing is written down, and one press undoes it. The press has to exist for that
    argument to hold, so it is asserted here rather than remembered."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    board = (TEMPLATES / "board.html").read_text(encoding="utf-8")

    assert "data-lay" in board and 'id="lay-panel"' in board
    assert "data-lay-back" in board, "an arrangement with no way back is one nobody will try twice"

    back = console[console.index("function putItBack(") :]
    back = back[: back.index("\n}\n")]
    assert "layoutBefore" in back and "rememberLayout()" in back

    laying = console[console.index("function layOutInColumns(") :]
    laying = laying[: laying.index("\n}\n")]
    assert "layoutBefore = new Map(placed)" in laying, (
        "the way back is not recorded before the way there"
    )
    assert "avoid: false" in laying, (
        "collision avoidance would nudge a card out of the column the answer put it in"
    )
    assert "columnHeads.push(" in laying, "a column without a heading is a pile"


@pytest.mark.unit
def test_the_headings_are_recalled_after_the_state_they_read_exists() -> None:
    """`columnHeads` is a `let`, and a top-level call before its declaration has run throws on the
    way past — which on a script with no module boundary means every line after it never runs. The
    console would come up with no workbench at all, and the only clue would be in the log."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert console.index("let columnHeads") < console.index("\nrecallColumns();")


@pytest.mark.unit
def test_what_the_model_is_told_about_a_card_is_what_the_card_already_shows() -> None:
    """Nothing is opened in order to arrange it: the kind, the name and the one line under it are
    what is on the screen in front of whoever asked."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    says = console[console.index("function sayWhatACardIs(") :]
    says = says[: says.index("\n}\n")]
    assert ".pin-label" in says and ".pin-hint" in says
    assert ".pin-body" not in says, "arranging a card opens it"


# --- and the route, which is one model call and no writes ----------------------------------------


async def _lay_out(said: str, cards: str, reply: str, monkeypatch: pytest.MonkeyPatch):
    """The route, with the model replaced. Nothing here starts a `claude -p`."""
    from agent_desk.web import routes

    async def fake(prompt: str):
        yield reply

    monkeypatch.setattr(routes.answer_session, "stream_answer", fake)

    from tests.unit.test_input import _post

    return await _post("/workbench/columns", {"said": said, "cards": cards})


@pytest.mark.unit
async def test_the_route_answers_columns_of_numbers_and_the_cards_left_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Numbers, in the order the page sent them: where a card sits is a fact about a browser, and
    this program has no view on it."""
    import json

    status, body, _ = await _lay_out(
        "справа те что интересны разработчикам",
        "idea — a parser\nidea — a colour scheme\nsession — biba",
        "for developers | 1\nfor everybody else | 2\n",
        monkeypatch,
    )

    assert status == 200
    said = json.loads(body)
    assert said["laid"] is True
    assert said["columns"] == [
        {"title": "for developers", "cards": [1]},
        {"title": "for everybody else", "cards": [2]},
    ]
    assert said["left"] == [3]


@pytest.mark.unit
async def test_the_route_moves_nothing_when_the_reply_is_not_an_arrangement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half an arrangement reads as an answer and is not one, so none of it is sent."""
    status, body, _ = await _lay_out(
        "sort them", "idea — one", "I would put the first one on the right.", monkeypatch
    )

    assert status == 422
    assert "could read" in body


@pytest.mark.unit
async def test_the_route_wants_both_a_request_and_something_to_arrange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, _, _ = await _lay_out("   ", "idea — one", "one | 1", monkeypatch)
    assert status == 400

    status, _, _ = await _lay_out("sort them", "   ", "one | 1", monkeypatch)
    assert status == 400


@pytest.mark.unit
async def test_the_route_says_so_when_there_is_no_engine_to_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same answer every other model call in this program gives: a refusal with the reason in
    it, rather than a five hundred."""
    from agent_desk.web import routes

    async def gone(prompt: str):
        raise routes.answer_session.AnswerFailed("there is no claude on this machine")
        yield ""

    monkeypatch.setattr(routes.answer_session, "stream_answer", gone)

    from tests.unit.test_input import _post

    status, body, _ = await _post(
        "/workbench/columns", {"said": "sort them", "cards": "idea — one"}
    )

    assert status == 502
    assert "no claude" in body
