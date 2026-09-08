"""A connector opens out into what is inside it, over the network
(01M1X8DA5X4ZYN98YK0N5QT5W9).

"Если это jira — должны при раскрытии отображаться карточки колонок jira, которые в свою очередь
имеют карточки тикетов. Тот же механизм раскрытия, но через сеть: у коннектора спрашивают, что у
него внутри, уровень за уровнем."

The mechanism is the one a project already opens out with; what is new is that a connector's
insides are not on the page. A project's checkouts and sessions are rendered in the left column, so
the page reads them from there; a board's columns are behind somebody else's API and have to be
asked for.

The constraint is unchanged: we read, we do not write (docs/adr/0010).
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import roles
from agent_desk.store.repo import BoardTicket, Store
from agent_desk.tracker import jira
from agent_desk.web import routes

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)
KEY = "origin:acme/api"
JIRA = "https://acme.atlassian.net/browse/API"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


async def _a_board(store: Store) -> None:
    await store.set_link(repo_key=KEY, name="jira", url=JIRA, token_env="JIRA_TOKEN")
    await store.replace_tickets(
        KEY,
        [
            BoardTicket(repo_key=KEY, key="API-1", summary="one", status="To Do", seen_at=0),
            BoardTicket(repo_key=KEY, key="API-2", summary="two", status="To Do", seen_at=0),
            BoardTicket(repo_key=KEY, key="API-3", summary="three", status="Backlog", seen_at=0),
        ],
    )


def _parts(answer: object) -> list[dict[str, str]]:
    return json.loads(bytes(answer.body).decode())["parts"]  # type: ignore[attr-defined]


# --- a connector opens into columns ------------------------------------------------------------------
async def test_a_jira_connector_opens_into_the_columns_of_its_board(desk: Store) -> None:
    await _a_board(desk)

    parts = _parts(await routes.parts_of_a_card("connector", f"{KEY}::jira"))

    assert [one["kind"] for one in parts] == ["column", "column"]
    assert {one["id"] for one in parts} == {f"{KEY}::To Do", f"{KEY}::Backlog"}


async def test_a_column_says_how_many_are_standing_in_it(desk: Store) -> None:
    """A column card that only said "To Do" would make somebody open it to find out whether it is
    worth opening."""
    await _a_board(desk)

    parts = _parts(await routes.parts_of_a_card("connector", f"{KEY}::jira"))
    labels = {one["id"]: one["label"] for one in parts}

    assert labels[f"{KEY}::To Do"] == "To Do · 2 tickets"
    assert labels[f"{KEY}::Backlog"] == "Backlog · 1 ticket"


async def test_a_connector_this_console_cannot_read_has_nothing_inside(desk: Store) -> None:
    """A Slack link, a wiki, a Jira with no credential. An empty list is a true answer and not an
    error — "nothing inside this one" is what the page says."""
    await desk.set_link(repo_key=KEY, name="slack", url="https://acme.slack.com/x")

    assert _parts(await routes.parts_of_a_card("connector", f"{KEY}::slack")) == []


async def test_a_connector_that_is_not_there_has_nothing_inside(desk: Store) -> None:
    assert _parts(await routes.parts_of_a_card("connector", f"{KEY}::nothing")) == []


async def test_an_unread_board_is_read_when_it_is_opened(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opening a connector is asking what is in it, and an empty answer out of a board nobody has
    read yet is the wrong answer to that question."""
    from agent_desk.web import blocks

    await desk.set_link(repo_key=KEY, name="jira", url=JIRA, token_env="JIRA_TOKEN")
    monkeypatch.setattr(
        blocks.jira,
        "read_board",
        lambda where: jira.Read(
            ok=True, tickets=(jira.Ticket(key="API-9", summary="read now", status="Open"),)
        ),
    )

    parts = _parts(await routes.parts_of_a_card("connector", f"{KEY}::jira"))

    assert [one["id"] for one in parts] == [f"{KEY}::Open"]


async def test_a_board_that_could_not_be_read_has_nothing_inside(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_desk.web import blocks

    await desk.set_link(repo_key=KEY, name="jira", url=JIRA, token_env="JIRA_TOKEN")
    monkeypatch.setattr(blocks.jira, "read_board", lambda where: jira.Read(ok=False, detail="401"))

    assert _parts(await routes.parts_of_a_card("connector", f"{KEY}::jira")) == []


# --- and a column into its tickets ---------------------------------------------------------------
async def test_a_column_opens_into_the_tickets_standing_in_it(desk: Store) -> None:
    await _a_board(desk)

    parts = _parts(await routes.parts_of_a_card("column", f"{KEY}::To Do"))

    assert [one["id"] for one in parts] == [f"{KEY}::API-1", f"{KEY}::API-2"]
    assert all(one["kind"] == "ticket" for one in parts)


async def test_a_ticket_with_no_status_stands_in_a_column_that_says_so(desk: Store) -> None:
    """Not in "To Do" and not nowhere. A board row this console read with no status is a row with
    no status, and putting it in the first column would be inventing one."""
    await desk.set_link(repo_key=KEY, name="jira", url=JIRA, token_env="JIRA_TOKEN")
    await desk.replace_tickets(
        KEY, [BoardTicket(repo_key=KEY, key="API-4", summary="four", seen_at=0)]
    )

    parts = _parts(await routes.parts_of_a_card("connector", f"{KEY}::jira"))

    assert [one["id"] for one in parts] == [f"{KEY}::no column"]


async def test_a_kind_with_nothing_behind_it_answers_with_nothing(desk: Store) -> None:
    assert _parts(await routes.parts_of_a_card("session", "abc")) == []


# --- the card, and what it does not claim ------------------------------------------------------------
async def test_the_column_card_lists_what_is_in_it(desk: Store) -> None:
    await _a_board(desk)

    answer = await routes.card("column", f"{KEY}::To Do")
    body = bytes(answer.body).decode()

    assert answer.status_code == 200
    assert "API-1" in body and "API-2" in body
    assert "API-3" not in body


async def test_the_column_card_says_it_is_not_the_whole_board(desk: Store) -> None:
    """This console reads the unfinished part of a board, so the columns it can show are the ones
    something unfinished is standing in. Letting somebody believe otherwise would be the fifth rule
    of CLAUDE.md in the shape of a diagram."""
    await _a_board(desk)

    body = bytes((await routes.card("column", f"{KEY}::To Do")).body).decode()

    assert "not the whole board" in body
    assert "moves a ticket between columns" in body


async def test_a_column_is_a_thing_that_exists() -> None:
    assert roles.role_of("column").name == "object"


# --- the page asks, where it cannot read -----------------------------------------------------------
def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def test_the_page_asks_only_for_the_kinds_it_cannot_read() -> None:
    """Asking for every card's parts on every board push would be a request every two seconds."""
    source = _code()

    assert "const ASK_FOR_PARTS = new Set(['connector', 'column'])" in source


def test_one_press_means_one_thing_on_either_side_of_the_wire() -> None:
    source = _code()
    start = source.index("async function openItsParts(")
    body = source[start : source.index("\n}\n", start)]

    assert "ASK_FOR_PARTS.has(what)" in body
    assert "askForParts(holder)" in body
    assert "partsOf(name).map(" in body


def test_a_card_with_nothing_inside_says_so() -> None:
    """It is the answer to a press, and a press that produces nothing and says nothing is a press
    somebody repeats."""
    source = _code()
    start = source.index("async function openItsParts(")
    body = source[start : source.index("\n}\n", start)]

    assert "Nothing inside this ${what} that this console can read." in body
