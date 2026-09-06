"""What the console does to answer one page, and the three things it used to do for nothing.

None of this is a benchmark — a timing assertion on somebody else's machine is a test that fails
for the weather. These assert the *shape* that made it slow: a query per row of a list that was
already being read whole, and a file read per session for a field nobody looked at.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.ideas import inbox
from agent_desk.store.repo import Store
from agent_desk.web import routes

ROUTES = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "routes.py"
KEY = "origin:acme/api"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _body(name: str) -> ast.AST:
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not in routes.py any more")


@pytest.mark.unit
def test_shape_reads_only_the_session_and_never_its_transcript() -> None:
    """`sessions_only` hands `shape` rows with no tail on them, because reading one costs a file
    open per session and `shape` groups by working directory.

    If `shape` ever starts looking at `row.tail` or `row.hint`, that becomes a page quietly built
    from `None` — which is the failure this asserts against, in the only place it can be seen.
    """
    fields = {
        node.attr
        for node in ast.walk(_body("shape"))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    }

    assert "tail" not in fields, (
        "shape reads a transcript tail now, so sessions_only hands it None — either read the "
        "board there or stop reading tails here"
    )
    assert "hint" not in fields


@pytest.mark.unit
def test_asking_which_projects_exist_does_not_open_a_single_transcript() -> None:
    """The board's expensive half is one file read per live session. Anything that only wants the
    list of projects was paying for all of them."""
    # Every name the function mentions: `board` and `sessions_only` are both handed to
    # `to_thread` rather than called, so looking only at call targets would find neither.
    names = {node.id for node in ast.walk(_body("_project_choices")) if isinstance(node, ast.Name)}

    assert "sessions_only" in names
    assert "board" not in names, "the whole board is read again to get a list of project names"


@pytest.mark.unit
async def test_the_inbox_reads_every_draft_in_one_query(desk: Store) -> None:
    """It used to ask per idea — one connection and one statement each, awaited in order, for
    every idea somebody has ever written down."""
    first = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    second = await inbox.capture(desk, "something else", project_key=KEY)
    await desk.create_draft(idea_id=first.id, kind="ticket", body="one")
    await desk.create_draft(idea_id=first.id, kind="proposal", body="two")

    found = await desk.drafts_by_idea()

    assert [draft.body for draft in found[first.id]] == ["two", "one"]
    assert second.id not in found, "an idea with no drafts is a key with an empty list"
    # And it agrees with the query it replaced, which is the only thing that matters about it.
    assert found[first.id] == await desk.drafts_for(first.id)


@pytest.mark.unit
async def test_what_was_written_about_many_cards_comes_back_in_one_query(desk: Store) -> None:
    await desk.say_card("idea:one", "a sentence about one", "from the text")
    await desk.say_card("idea:two", "a sentence about two", "from the text")

    found = await desk.cards_said(["idea:one", "idea:two", "idea:missing"])

    assert found == {"idea:one": "a sentence about one", "idea:two": "a sentence about two"}
    assert await desk.cards_said([]) == {}, "an empty page must not become a query with no bounds"


@pytest.mark.unit
async def test_a_card_name_with_a_quote_in_it_is_bound_and_not_interpolated(
    desk: Store,
) -> None:
    """The names are built from ids that came off a card in the page. They are bound parameters,
    and this is the test that says so rather than a comment claiming it."""
    await desk.say_card("idea:x", "kept", "from the text")

    found = await desk.cards_said(["idea:' OR 1=1 --", "idea:x"])

    assert found == {"idea:x": "kept"}


@pytest.mark.unit
async def test_the_ideas_column_still_says_what_was_written_about_each_one(desk: Store) -> None:
    """The bulk read is keyed by card name and the column wants idea ids. A fast path that
    returns the right rows under the wrong keys shows every card an empty sentence."""
    idea = await inbox.capture(desk, "cache the probe results", project_key=KEY)
    await desk.say_card(f"idea:{idea.id}", "already built, in dispatch.py", "from a filing")
    await desk.appraise_idea(idea.id, size="small", shape="built")

    html = await routes.render_ideas()

    assert "already built, in dispatch.py" in html
    assert "This reads like something that already exists" not in html, (
        "the evidence did not reach the card, so a fact is being offered as a hunch"
    )
