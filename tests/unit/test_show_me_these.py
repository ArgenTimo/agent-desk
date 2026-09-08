"""Ask for things in words and get them on the workbench (01M1ZQ3JQ4PS5B0GPAB156H5HP).

"И способ попросить: «покажи тикеты из спринта», «покажи открытые PR-ы»."

Everything that reaches the bench got there by being dragged or by an answer that drew it. This
composes nothing and decides nothing: a list is read from the place that has it, each row becomes a
card, and the block says which list it read.

The last of the three children of "Вынести на верстак то, к чему есть доступ"
(01M1X8DA5KM5K6VZDKWKM664Y0).
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import roles, showing, telling
from agent_desk.answer import classify
from agent_desk.store.repo import BoardTicket, Store
from agent_desk.web import blocks, routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
BLOCKS_HTML = HERE / "agent_desk" / "web" / "templates" / "_blocks.html"
KEY = "origin:acme/api"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


# --- reading the request --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "said",
    ["покажи открытые PR-ы", "show me the open pull requests", "вынеси пулл-реквесты на верстак"],
)
def test_a_request_for_pull_requests(said: str) -> None:
    assert showing.what_to_show(said) == "pulls"


@pytest.mark.parametrize("said", ["покажи тикеты из спринта", "put the tickets on the bench"])
def test_a_request_for_tickets(said: str) -> None:
    assert showing.what_to_show(said) == "tickets"


def test_a_request_for_neither_is_neither() -> None:
    """The closed list is the point: two things this console can read, and anything else it is
    asked for it cannot fetch (docs/adr/0010)."""
    assert showing.what_to_show("покажи мне процесс релиза") == ""
    assert set(showing.WHAT) == {"tickets", "pulls"}


def test_a_request_naming_both_takes_the_pull_requests() -> None:
    """Not arbitrary. Answering the tickets half of "покажи тикеты и PR-ы" is a wrong guess that
    looks like the whole answer; answering the other half is a wrong guess somebody can see."""
    assert showing.what_to_show("покажи тикеты и PR-ы") == "pulls"


def test_it_is_read_here_rather_than_asked_of_a_model() -> None:
    """The same argument `waking` is served under: it cannot fail on a busy machine or a spent
    budget, and what it decides is which of two lists to fetch — a decision with an answer."""
    source = (HERE / "agent_desk" / "showing.py").read_text(encoding="utf-8")

    assert "stream_answer" not in source
    assert "async def" not in source


# --- the classifier -------------------------------------------------------------------------------
def test_show_is_one_of_the_kinds() -> None:
    assert classify.read_kind("show") == "showing"


def test_the_prompt_says_what_show_is_and_what_it_is_not() -> None:
    asked = classify.kind_prompt("покажи открытые PR-ы")

    assert "show " in asked
    # The list is not counted in the instruction any more — a number that has to be kept in step
    # with the list below it is a number that will not be.
    assert "Say which of these it is" in asked
    assert "wants a number" in asked, "the boundary against `question` is not drawn"


def test_the_page_says_what_it_took_the_line_for() -> None:
    assert "workbench" in telling.taken_as("showing")


# --- which project --------------------------------------------------------------------------------
def test_the_project_on_the_workbench_is_the_one() -> None:
    """A card on the bench is what somebody is pointing at, and pointing is how everything else in
    this console says which thing it means."""
    assert blocks._which_project((), [f"project:{KEY}", "idea:one"]) == KEY


def test_a_project_is_never_guessed_from_the_words() -> None:
    """A project key is a URL, nobody types one, and matching a name out of a line is a guess that
    reads somebody else's board with somebody else's credential."""
    source = (HERE / "agent_desk" / "web" / "blocks.py").read_text(encoding="utf-8")
    start = source.index("def _which_project(")
    body = source[start : source.index("\n\n\n", start)]

    assert "block.input" not in body


def test_nothing_to_point_at_is_a_real_answer() -> None:
    """Reading the wrong board is worse than asking which one."""
    assert blocks._which_project((), ["idea:one"]) == ""


# --- what comes back ------------------------------------------------------------------------------
async def test_a_request_naming_neither_says_what_can_be_asked_for(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="покажи мне что-нибудь", thread_set_by="human"
    )

    await blocks._show_them(desk, block, (), [])

    again = await desk.block(block.id)
    assert again is not None
    assert "tickets on a project's board" in (again.answer or "")
    assert again.kind == "showing"


async def test_a_project_with_no_connector_says_so_and_where_to_say_it(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="покажи открытые PR-ы", thread_set_by="human"
    )

    await blocks._show_them(desk, block, (), [f"project:{KEY}"])

    again = await desk.block(block.id)
    assert again is not None
    assert "no GitHub link with a credential" in (again.answer or "")


async def test_what_was_read_becomes_cards_the_page_puts_on_the_bench(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="покажи тикеты", thread_set_by="human"
    )

    async def read(_store: Store, key: str) -> tuple[list[str], str]:
        await _store.replace_tickets(
            key,
            [
                BoardTicket(
                    repo_key=key, key="API-14", summary="the slash", status="To Do", seen_at=0
                )
            ],
        )
        return [f"ticket:{key}::API-14"], ""

    monkeypatch.setattr(blocks, "read_tickets_now", read)

    await blocks._show_them(desk, block, (), [f"project:{KEY}"])

    again = await desk.block(block.id)
    assert again is not None
    said, cards = telling.read_drawn(again.answer or "")
    assert cards == [f"ticket:{KEY}::API-14"]
    assert "API-14" in said
    assert "read just now" in said


async def test_an_empty_board_says_it_was_empty(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which is a different sentence from "I could not read it", and they must not look alike."""
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="покажи тикеты", thread_set_by="human"
    )

    async def nothing(_store: Store, _key: str) -> tuple[list[str], str]:
        return [], ""

    monkeypatch.setattr(blocks, "read_tickets_now", nothing)

    await blocks._show_them(desk, block, (), [f"project:{KEY}"])

    again = await desk.block(block.id)
    assert again is not None and "came back empty" in (again.answer or "")


async def test_a_read_that_failed_says_why(desk: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="покажи тикеты", thread_set_by="human"
    )

    async def broken(_store: Store, _key: str) -> tuple[list[str], str]:
        return [], "I could not read the board: 401"

    monkeypatch.setattr(blocks, "read_tickets_now", broken)

    await blocks._show_them(desk, block, (), [f"project:{KEY}"])

    again = await desk.block(block.id)
    assert again is not None and "401" in (again.answer or "")


async def test_showing_tickets_queues_no_work(desk: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """Putting a ticket in this console's queue is a decision `autostart.pull_tickets` makes
    deliberately. Looking at a board must not make it as a side effect (docs/adr/0010)."""
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="покажи тикеты", thread_set_by="human"
    )

    async def read(_store: Store, key: str) -> tuple[list[str], str]:
        await _store.replace_tickets(
            key, [BoardTicket(repo_key=key, key="API-14", summary="x", seen_at=0)]
        )
        return [f"ticket:{key}::API-14"], ""

    monkeypatch.setattr(blocks, "read_tickets_now", read)

    await blocks._show_them(desk, block, (), [f"project:{KEY}"])

    assert await desk.tasks() == []


# --- and the cards themselves -----------------------------------------------------------------------
async def test_a_ticket_read_from_a_board_is_a_card(desk: Store) -> None:
    await desk.replace_tickets(
        KEY,
        [BoardTicket(repo_key=KEY, key="API-14", summary="the slash", status="To Do", seen_at=0)],
    )

    answer = await routes.card("ticket", f"{KEY}::API-14")
    body = bytes(answer.body).decode()

    assert answer.status_code == 200
    assert "the slash" in body
    assert "To Do" in body
    assert "this console reads" in body


async def test_a_stuck_ticket_quotes_its_own_words(desk: Store) -> None:
    await desk.replace_tickets(
        KEY,
        [
            BoardTicket(
                repo_key=KEY, key="API-15", summary="x", blocked_by="waiting on design", seen_at=0
            )
        ],
    )

    body = bytes((await routes.card("ticket", f"{KEY}::API-15")).body).decode()

    assert "waiting on design" in body


async def test_a_ticket_is_a_thing_and_the_task_for_it_is_the_decision_to_do_it() -> None:
    assert roles.role_of("ticket").name == "object"
    assert roles.role_of("task").name == "action"


def test_the_cards_reach_the_bench_through_the_mechanism_that_already_existed() -> None:
    """A drawing message already put cards on the bench by listing them under its answer. A second
    way of doing that would be a second thing to keep in step."""
    markup = BLOCKS_HTML.read_text(encoding="utf-8")

    assert 'block.kind in ("drawing", "showing")' in markup
    assert 'class="drawn-cards"' in markup


# --- the readers themselves -------------------------------------------------------------------------
async def test_the_pull_requests_are_read_and_kept(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read fresh rather than shown from the store: "покажи" is asked when somebody wants to know
    what is there now, and a cache with nothing saying how old it is answers a different question."""
    from agent_desk.tracker import github

    await desk.set_link(
        repo_key=KEY, name="github", url="https://github.com/acme/api", token_env="GH_TOKEN"
    )

    def one_pull(repo: str, token_env: str) -> github.Read:
        assert (repo, token_env) == ("acme/api", "GH_TOKEN")
        return github.Read(
            ok=True,
            pulls=(
                github.Pull(
                    number=12,
                    title="drop the slash",
                    url="https://github.com/acme/api/pull/12",
                    waiting_for="a review",
                ),
            ),
        )

    monkeypatch.setattr(blocks.github, "open_pulls", one_pull)

    cards, why = await blocks._read_pulls(desk, KEY)

    assert why == ""
    assert cards == [f"pull:{KEY}::#12"]
    (kept,) = await desk.pulls(KEY)
    assert (kept.number, kept.waiting_for) == (12, "a review")


async def test_a_github_read_that_failed_says_what_it_said(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_desk.tracker import github

    await desk.set_link(
        repo_key=KEY, name="github", url="https://github.com/acme/api", token_env="GH_TOKEN"
    )
    monkeypatch.setattr(
        blocks.github,
        "open_pulls",
        lambda repo, token_env: github.Read(ok=False, detail="401 bad credentials"),
    )

    cards, why = await blocks._read_pulls(desk, KEY)

    assert cards == []
    assert "401 bad credentials" in why


async def test_a_link_with_no_credential_is_not_a_way_in(desk: Store) -> None:
    """ "A project with a link and no variable has a link, not a destination."""
    await desk.set_link(repo_key=KEY, name="github", url="https://github.com/acme/api")

    cards, why = await blocks._read_pulls(desk, KEY)

    assert cards == []
    assert "no GitHub link with a credential" in why


async def test_the_board_is_read_and_kept(desk: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_desk.tracker import jira

    await desk.set_link(
        repo_key=KEY,
        name="jira",
        url="https://acme.atlassian.net/browse/API",
        token_env="JIRA_TOKEN",
    )

    def one_ticket(where: jira.Destination) -> jira.Read:
        return jira.Read(
            ok=True,
            tickets=(jira.Ticket(key="API-14", summary="the slash", status="To Do"),),
        )

    monkeypatch.setattr(blocks.jira, "read_board", one_ticket)

    cards, why = await blocks.read_tickets_now(desk, KEY)

    assert why == ""
    assert cards == [f"ticket:{KEY}::API-14"]
    (kept,) = await desk.board_tickets(KEY)
    assert (kept.key, kept.status) == ("API-14", "To Do")


async def test_a_board_read_that_failed_says_what_it_said(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_desk.tracker import jira

    await desk.set_link(
        repo_key=KEY,
        name="jira",
        url="https://acme.atlassian.net/browse/API",
        token_env="JIRA_TOKEN",
    )
    monkeypatch.setattr(
        blocks.jira, "read_board", lambda where: jira.Read(ok=False, detail="403 forbidden")
    )

    cards, why = await blocks.read_tickets_now(desk, KEY)

    assert cards == []
    assert "403 forbidden" in why


async def test_a_project_with_no_board_says_so(desk: Store) -> None:
    cards, why = await blocks.read_tickets_now(desk, KEY)

    assert cards == []
    assert "no board link with a credential" in why


async def test_the_only_project_there_is_needs_no_pointing(desk: Store) -> None:
    """One project on the board and no card on the bench: there is nothing to be wrong about."""

    class Row:
        project_key = KEY

    assert blocks._which_project([Row()], []) == KEY  # type: ignore[list-item]
