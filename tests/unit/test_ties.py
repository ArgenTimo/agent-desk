"""What a line between two cards means, and why it has to mean something.

A line that says only "these two are related" is a picture: read a bench of them and you learn
that somebody thought six things belong together, which you already knew, because they are on the
same bench. These are the five that turn a picture into a sentence.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import ties
from agent_desk.store.repo import Store
from agent_desk.web import routes

STATIC = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


@pytest.mark.unit
def test_the_five_kinds_of_line() -> None:
    assert set(ties.KINDS) == {"then", "if", "when", "makes", "with"}


@pytest.mark.unit
def test_only_a_branch_is_meaningless_without_words_on_it() -> None:
    """ "If" with no condition is a fork nobody can follow. "Then" with nothing written on it is
    exactly as clear as it needs to be, and asking for a note on every line is how people stop
    drawing them."""
    wants = {name for name, one in ties.KINDS.items() if one.wants_words}

    assert wants == {"if"}


@pytest.mark.unit
def test_the_only_line_without_a_direction_is_the_one_without_an_order() -> None:
    """ "A goes with B" is the same statement as "B goes with A", and drawing an arrowhead on it
    would claim an order nobody said. The other four are all about what happens next."""
    both_ways = {name for name, one in ties.KINDS.items() if not one.one_way}

    assert both_ways == {"with"}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("out_of", "into", "expected"),
    [
        ("decision", "action", "if"),
        ("decision", "result", "if"),
        ("event", "action", "when"),
        ("action", "result", "makes"),
        ("action", "action", "then"),
        ("object", "action", "then"),
    ],
)
def test_a_line_is_decided_by_what_it_comes_out_of(out_of: str, into: str, expected: str) -> None:
    """Draw one out of a diamond and it is a branch before anybody has chosen anything. That is
    the whole of the ergonomics here — and note the second row: a branch into a Result is still a
    branch, because what the line *is* is decided by the end it leaves."""
    assert ties.natural(out_of, into) == expected


@pytest.mark.unit
def test_a_line_that_reads_strangely_is_mentioned_and_not_refused() -> None:
    """Somebody sketching a process is thinking, and the shapes catch up with the thought rather
    than the other way round. A constructor that rejects the line you drew because the boxes are
    not yet the right shape is a constructor you fight."""
    assert ties.odd_pair("if", "action", "action"), "a branch out of an Action passes unremarked"
    assert ties.odd_pair("when", "object", "action")
    assert ties.odd_pair("makes", "action", "object")

    assert ties.odd_pair("if", "decision", "action") == ""
    assert ties.odd_pair("then", "object", "event") == "", "an ordinary line is never odd"
    assert ties.odd_pair("with", "event", "decision") == ""


@pytest.mark.unit
async def test_a_line_joins_two_cards_of_any_kind(desk: Store) -> None:
    """The reason the ends are names and not ids: a process runs from an idea through a session to
    a blocker, and only one of those three is a row in this database."""
    await desk.tie_cards(
        from_name="idea:one", to_name="session:abc", kind="then", says="after it is decided"
    )

    (line,) = await desk.card_ties()
    assert (line.from_name, line.to_name, line.kind) == ("idea:one", "session:abc", "then")
    assert line.says == "after it is decided"


@pytest.mark.unit
async def test_drawing_the_same_line_twice_changes_it_rather_than_stacking(desk: Store) -> None:
    """Pressing twice is somebody pressing twice, not two relations — and a second line behind the
    first is invisible and undeletable."""
    await desk.tie_cards(from_name="a:1", to_name="b:2", kind="then")
    await desk.tie_cards(from_name="a:1", to_name="b:2", kind="if", says="when the gate is green")

    lines = await desk.card_ties()
    assert len(lines) == 1
    assert lines[0].kind == "if"
    assert lines[0].says == "when the gate is green"


@pytest.mark.unit
async def test_a_card_is_never_tied_to_itself(desk: Store) -> None:
    """It says nothing, and it draws as a dot on top of the card."""
    await desk.tie_cards(from_name="a:1", to_name="a:1", kind="then")

    assert await desk.card_ties() == []


@pytest.mark.unit
async def test_a_line_can_be_rubbed_out(desk: Store) -> None:
    await desk.tie_cards(from_name="a:1", to_name="b:2", kind="then")
    (line,) = await desk.card_ties()

    await desk.untie_cards(line.id)

    assert await desk.card_ties() == []


@pytest.mark.unit
async def test_the_route_refuses_a_kind_that_is_not_one_of_the_five(desk: Store) -> None:
    """Five words with a meaning each is a language; a free-text label with an arrow on it is a
    note. The same argument that keeps the roles to five."""
    from tests.unit.test_input import _post

    status, _, _ = await _post(
        "/workbench/tie", {"from": "a:1", "to": "b:2", "kind": "leads sort of towards"}
    )

    assert status == 400
    assert await desk.card_ties() == []


@pytest.mark.unit
async def test_the_route_draws_one_and_hands_back_the_five(desk: Store) -> None:
    from tests.unit.test_input import _post

    status, _, _ = await _post(
        "/workbench/tie", {"from": "a:1", "to": "b:2", "kind": "if", "says": "if it fails"}
    )
    assert status == 200

    answer = await routes.workbench_lines()
    body = bytes(answer.body).decode()

    assert "if it fails" in body
    for name in ties.KINDS:
        assert f'"{name}"' in body
    assert "ordinarily" in body, "the page is not told what an ordinary line is"


@pytest.mark.unit
def test_the_console_asks_for_the_five_rather_than_listing_them() -> None:
    """Same rule as the roles: a second list is a second place to be wrong, silently."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "'/workbench/lines'" in console
    assert "function naturalTie(" in console
    natural = console[console.index("function naturalTie(") :]
    natural = natural[: natural.index("\n}\n")]
    assert "tieFromRole" in natural and "tieIntoRole" in natural, (
        "the page works out what a line is from its own copy of the rule"
    )


@pytest.mark.unit
def test_only_a_line_somebody_drew_can_be_changed() -> None:
    """The ones this console works out for itself — which project a session is in, what a question
    went out with — are readings of facts. A menu offering to edit one would be offering to edit
    the fact."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "if (tie.drawn) {" in console
    assert "drawn: true" in console
