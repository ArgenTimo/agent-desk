"""Lines between cards from different places, named the way the source names them
(01M1X8DA65QGXJNA31SHJ9X3YW).

"Связь тикет↔PR существует в чужих системах, и её надо показывать так, как называется там: PRs,
blocks, relates to… Правило то же, что и везде: линию рисуем только если её кто-то записал — там
или здесь. Связь по совпадению названий рисовать нельзя, это догадка."

Two halves. The label is the source's own words, which is what the sixth line kind was added for.
And a line exists only where a row records it — never because two cards mention the same string.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.ideas import bench
from agent_desk.store.repo import Store, TicketLink
from agent_desk.tracker import jira
from agent_desk.web import routes

pytestmark = pytest.mark.unit

KEY = "origin:acme/api"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _board(*links: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "issues": [
                {
                    "key": "API-1",
                    "fields": {
                        "summary": "a thing",
                        "status": {"name": "To Do"},
                        "issuelinks": list(links),
                    },
                }
            ]
        }
    ).encode()


# --- what the board says --------------------------------------------------------------------------
def test_a_link_keeps_the_boards_own_words() -> None:
    (ticket,) = jira.read_tickets(
        _board(
            {
                "type": {"name": "Blocks", "outward": "blocks", "inward": "is blocked by"},
                "outwardIssue": {"key": "API-2"},
            }
        )
    )

    assert ticket.links == (jira.Link(says="blocks", key="API-2"),)


def test_the_side_decides_the_words() -> None:
    """Reading the wrong one produces a line saying "blocks" pointing at the ticket doing the
    blocking."""
    (ticket,) = jira.read_tickets(
        _board(
            {
                "type": {"name": "Blocks", "outward": "blocks", "inward": "is blocked by"},
                "inwardIssue": {"key": "API-3"},
            }
        )
    )

    assert ticket.links == (jira.Link(says="is blocked by", key="API-3"),)


def test_a_link_with_no_wording_falls_back_to_the_types_name() -> None:
    (ticket,) = jira.read_tickets(
        _board({"type": {"name": "Duplicate"}, "outwardIssue": {"key": "API-4"}})
    )

    assert ticket.links == (jira.Link(says="Duplicate", key="API-4"),)


def test_something_shaped_differently_is_skipped_rather_than_guessed_at() -> None:
    (ticket,) = jira.read_tickets(_board({"nonsense": 1}, {"type": {}, "outwardIssue": {}}))

    assert ticket.links == ()


def test_a_board_with_no_links_field_reads_fine() -> None:
    raw = json.dumps({"issues": [{"key": "API-1", "fields": {"summary": "a"}}]}).encode()

    (ticket,) = jira.read_tickets(raw)
    assert ticket.links == ()


def test_the_field_is_asked_for() -> None:
    """A `fields` list is the difference between a response that is read and a whole issue
    including its attachments — so a new field has to be named."""
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "tracker" / "jira.py"
    ).read_text(encoding="utf-8")

    assert '"fields": "summary,status,description,issuelinks"' in source


# --- what gets drawn ------------------------------------------------------------------------------
class _Link:
    repo_key, key, says, other = KEY, "API-1", "blocks", "API-2"


class _Task:
    id, repo_key, source_kind, source_ref = "t1", KEY, "tracker", "API-1"


class _Filing:
    idea_id, issue_key = "i1", "API-1"


def test_the_boards_link_becomes_a_line_with_its_words() -> None:
    drawn = bench.recorded_ties(
        [f"ticket:{KEY}::API-1", f"ticket:{KEY}::API-2"], ticket_links=[_Link()]
    )

    assert drawn == [
        {"from": f"ticket:{KEY}::API-1", "to": f"ticket:{KEY}::API-2", "says": "blocks"}
    ]


def test_a_task_says_it_was_read_from_the_board() -> None:
    """Recorded here, so the wording is ours — and it is a claim this program can stand behind."""
    drawn = bench.recorded_ties([f"ticket:{KEY}::API-1", "task:t1"], tasks=[_Task()])

    assert drawn == [
        {"from": f"ticket:{KEY}::API-1", "to": "task:t1", "says": "read from the board"}
    ]


def test_an_idea_filed_as_a_ticket_says_so() -> None:
    drawn = bench.recorded_ties([f"ticket:{KEY}::API-1", "idea:i1"], filings=[_Filing()])

    assert drawn == [{"from": "idea:i1", "to": f"ticket:{KEY}::API-1", "says": "filed as"}]


def test_a_task_queued_by_hand_is_joined_to_no_ticket() -> None:
    """`source_ref` is only a ticket key when the task came off a board."""

    class Queued:
        id, repo_key, source_kind, source_ref = "t2", KEY, "human", "API-1"

    assert bench.recorded_ties([f"ticket:{KEY}::API-1", "task:t2"], tasks=[Queued()]) == []


def test_nothing_is_drawn_from_two_cards_mentioning_the_same_string() -> None:
    """The rule the whole idea turns on. A ticket key in a pull request's title is a coincidence
    until somebody records that it is not."""
    drawn = bench.recorded_ties([f"ticket:{KEY}::API-1", f"pull:{KEY}::#12"])

    assert drawn == []


def test_a_line_with_one_end_off_the_bench_is_not_drawn() -> None:
    assert bench.recorded_ties([f"ticket:{KEY}::API-1"], ticket_links=[_Link()]) == []


def test_a_ticket_linked_to_itself_draws_nothing() -> None:
    class Itself:
        repo_key, key, says, other = KEY, "API-1", "relates to", "API-1"

    assert bench.recorded_ties([f"ticket:{KEY}::API-1"], ticket_links=[Itself()]) == []


def test_another_projects_ticket_with_the_same_key_is_a_different_card() -> None:
    """A ticket key means nothing outside the board it is on, which is why the card name carries
    the project."""
    drawn = bench.recorded_ties(
        [f"ticket:{KEY}::API-1", "ticket:origin:acme/web::API-2"], ticket_links=[_Link()]
    )

    assert drawn == []


# --- and the route hands them to the page -----------------------------------------------------------
async def test_the_page_is_given_them_alongside_the_ones_it_already_had(desk: Store) -> None:
    await desk.replace_ticket_links(
        KEY, [TicketLink(repo_key=KEY, key="API-1", says="blocks", other="API-2")]
    )

    answer = await routes.workbench_ties(f"ticket:{KEY}::API-1,ticket:{KEY}::API-2")
    drawn = json.loads(bytes(answer.body).decode())

    assert {"from": f"ticket:{KEY}::API-1", "to": f"ticket:{KEY}::API-2", "says": "blocks"} in drawn


async def test_the_links_are_kept_with_the_tickets_they_came_with(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_desk.web import blocks

    await desk.set_link(
        repo_key=KEY,
        name="jira",
        url="https://acme.atlassian.net/browse/API",
        token_env="JIRA_TOKEN",
    )
    monkeypatch.setattr(
        blocks.jira,
        "read_board",
        lambda where: jira.Read(
            ok=True,
            tickets=(
                jira.Ticket(
                    key="API-1",
                    summary="a thing",
                    links=(jira.Link(says="blocks", key="API-2"),),
                ),
            ),
        ),
    )

    await blocks._read_tickets(desk, KEY)

    assert await desk.ticket_links(KEY) == [
        TicketLink(repo_key=KEY, key="API-1", says="blocks", other="API-2")
    ]
