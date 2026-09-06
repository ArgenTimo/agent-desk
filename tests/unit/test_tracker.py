"""The one door out to a tracker, and everything it refuses to do (docs/adr/0005).

The transport is replaced here rather than mocked at the library level: what is worth asserting is
the request this program would make, and the ways it declines to make one at all.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import urllib.error
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import Store
from agent_desk.tracker import jira
from agent_desk.web import routes

SITE = "https://acme.atlassian.net"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


@pytest.mark.unit
def test_a_link_is_only_a_destination_when_it_names_both_halves() -> None:
    """The URL somebody pastes from their browser, and a variable they said to read."""
    destination = jira.destination_of(f"{SITE}/browse/API", "ACME_JIRA")
    assert destination is not None
    assert destination.site == SITE
    assert destination.project_key == "API"

    # No variable is not a destination: this program does not reach for an ambient credential.
    assert jira.destination_of(f"{SITE}/browse/API", None) is None
    assert jira.destination_of(f"{SITE}/browse/API", "") is None

    # And the URL is validated rather than trusted — it is interpolated into a request.
    assert jira.destination_of("http://acme.atlassian.net/browse/API", "T") is None
    assert jira.destination_of(f"{SITE}/browse/api", "T") is None
    assert jira.destination_of(f"{SITE}/projects/API/board", "T") is None
    assert jira.destination_of("javascript:alert(1)//browse/API", "T") is None


@pytest.mark.unit
def test_the_shape_of_the_value_decides_the_scheme() -> None:
    """Jira Cloud takes `email:token` as Basic; a self-hosted PAT is a Bearer token.

    Asking a human to also configure which kind of credential they configured is a setting that
    exists to be got wrong.
    """
    assert jira._authorization("me@example.com:abc").startswith("Basic ")
    assert jira._authorization("a-personal-access-token") == "Bearer a-personal-access-token"


@pytest.mark.unit
def test_an_unset_variable_is_a_refusal_and_not_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing is sent, and the reason names the variable rather than guessing at the cause."""
    sent = []
    monkeypatch.setattr(jira, "_post", lambda *args: sent.append(args))
    monkeypatch.delenv("ACME_JIRA", raising=False)

    result = jira.file_issue(jira.Destination(SITE, "API", "ACME_JIRA"), "one", "two")

    assert not result.filed
    assert "ACME_JIRA is not set" in result.detail
    assert sent == []


@pytest.mark.unit
def test_the_request_carries_the_draft_and_the_credential_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_post(url: str, body: bytes, authorization: str) -> tuple[int, bytes]:
        seen.update(url=url, body=json.loads(body), authorization=authorization)
        return 201, b'{"id": "1", "key": "API-42"}'

    monkeypatch.setattr(jira, "_post", fake_post)
    monkeypatch.setenv("ACME_JIRA", "me@example.com:secret")

    result = jira.file_issue(
        jira.Destination(SITE, "API", "ACME_JIRA"),
        "Cache the probe results",
        "It re-runs four calls on every retry.\n\nAcceptance: one call per project.",
    )

    assert result.filed
    assert result.key == "API-42"
    assert result.url == f"{SITE}/browse/API-42"
    assert seen["url"] == f"{SITE}/rest/api/3/issue"
    assert str(seen["authorization"]).startswith("Basic ")

    body = seen["body"]
    assert isinstance(body, dict)
    assert body["fields"]["project"] == {"key": "API"}
    assert body["fields"]["summary"] == "Cache the probe results"
    # The draft, as two paragraphs, and nothing added to it on the way out.
    paragraphs = body["fields"]["description"]["content"]
    assert len(paragraphs) == 2
    assert paragraphs[0]["content"][0]["text"].startswith("It re-runs")


@pytest.mark.unit
def test_a_refusal_says_what_jira_said_and_never_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_post(url: str, body: bytes, authorization: str) -> tuple[int, bytes]:
        calls.append(url)
        return (
            400,
            b'{"errorMessages": [], "errors": {"issuetype": "valid issue type is required"}}',
        )

    monkeypatch.setattr(jira, "_post", fake_post)
    monkeypatch.setenv("ACME_JIRA", "token")

    result = jira.file_issue(jira.Destination(SITE, "API", "ACME_JIRA"), "one", "two")

    assert not result.filed
    assert "400" in result.detail
    assert "valid issue type is required" in result.detail
    assert len(calls) == 1


@pytest.mark.unit
def test_a_network_failure_never_quotes_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """The request carries an Authorization header; the reason is the type, not the call."""

    def explode(url: str, body: bytes, authorization: str) -> tuple[int, bytes]:
        raise TimeoutError("timed out")

    monkeypatch.setattr(jira, "_post", explode)
    monkeypatch.setenv("ACME_JIRA", "me@example.com:secret")

    result = jira.file_issue(jira.Destination(SITE, "API", "ACME_JIRA"), "one", "two")

    assert not result.filed
    assert "secret" not in result.detail
    assert SITE in result.detail


# --- the three human acts between a thought and an issue ------------------------------------------
@pytest.mark.unit
async def test_an_idea_cannot_be_filed_before_it_is_kept_and_drafted(desk: Store) -> None:
    """docs/adr/0005: keep it, draft it, file it — and the first two are checked in the route."""
    await desk.set_link(repo_key="k", name="jira", url=f"{SITE}/browse/API", token_env="ACME_JIRA")
    idea = await desk.create_idea(
        text_="cache the probes", summary="cache the probes", source_kind="typed", context={}
    )

    plan = await routes._to_file(idea.id)
    assert plan.stage == "gone"
    assert "after it is kept" in plan.detail

    await desk.set_idea_state(idea.id, "kept")
    plan = await routes._to_file(idea.id)
    assert plan.stage == "gone"
    assert "draft the ticket first" in plan.detail

    await desk.create_draft(idea_id=idea.id, kind="ticket", body="Cache probes\n\nAcceptance: one")
    plan = await routes._to_file(idea.id)
    assert plan.stage == "confirm"
    assert plan.body == "Cache probes\n\nAcceptance: one"


@pytest.mark.unit
async def test_without_a_destination_the_console_says_so_rather_than_offering_the_button(
    desk: Store,
) -> None:
    idea = await desk.create_idea(
        text_="cache the probe results", summary="cache the probe results", source_kind="typed"
    )
    await desk.set_idea_state(idea.id, "kept")
    await desk.create_draft(idea_id=idea.id, kind="ticket", body="Cache the probe results")

    plan = await routes._to_file(idea.id)
    assert plan.stage == "gone"
    assert "no project has a Jira link" in plan.detail

    # A link with no variable on it is a link, not a destination.
    await desk.set_link(repo_key="k", name="jira", url=f"{SITE}/browse/API")
    assert (await routes._to_file(idea.id)).stage == "gone"


@pytest.mark.unit
async def test_the_same_idea_cannot_be_filed_twice(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale page and a second tab are the ordinary case, and the one thing this must never do
    is create the same issue twice."""
    await desk.set_link(repo_key="k", name="jira", url=f"{SITE}/browse/API", token_env="ACME_JIRA")
    idea = await desk.create_idea(
        text_="a thought", summary="a thought", source_kind="typed", context={}
    )
    await desk.set_idea_state(idea.id, "kept")
    await desk.create_draft(idea_id=idea.id, kind="ticket", body="A thought")

    calls: list[str] = []

    def fake_post(url: str, body: bytes, authorization: str) -> tuple[int, bytes]:
        calls.append(url)
        return 201, b'{"key": "API-7"}'

    monkeypatch.setattr(jira, "_post", fake_post)
    monkeypatch.setenv("ACME_JIRA", "token")

    from tests.unit.test_input import _post

    status, first, _ = await _post(f"/ideas/{idea.id}/file", {"key": "k"}, htmx=True)
    assert status == 200
    assert "API-7" in first

    status, second, _ = await _post(f"/ideas/{idea.id}/file", {"key": "k"}, htmx=True)
    assert status == 200
    assert "API-7" in second
    assert len(calls) == 1, "the second click filed a second issue"

    filing = await desk.filing_of(idea.id)
    assert filing is not None and filing.issue_key == "API-7"


@pytest.mark.unit
async def test_nothing_reaches_the_tracker_without_a_request(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opening the panel is not filing: step one has no side effect at all."""
    await desk.set_link(repo_key="k", name="jira", url=f"{SITE}/browse/API", token_env="ACME_JIRA")
    idea = await desk.create_idea(
        text_="a thought", summary="a thought", source_kind="typed", context={}
    )
    await desk.set_idea_state(idea.id, "kept")
    await desk.create_draft(idea_id=idea.id, kind="ticket", body="A thought")

    monkeypatch.setattr(
        jira, "_post", lambda *args: pytest.fail("opening the panel sent a request")
    )
    panel = routes._panel(await routes._to_file(idea.id))

    assert "File it" in panel
    assert await desk.filing_of(idea.id) is None
    assert asyncio.get_running_loop() is not None


@pytest.mark.unit
async def test_a_filed_idea_leaves_the_column_and_keeps_its_key(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registered in the tracker is one of the three things that take an idea off the list — the
    others being a human pressing built and an agent dispatched for it finishing. A guess is never
    one of them (docs/05-ideas.md)."""
    await desk.set_link(repo_key="k", name="jira", url=f"{SITE}/browse/API", token_env="ACME_JIRA")
    idea = await desk.create_idea(
        text_="a thought", summary="a thought", source_kind="typed", context={}
    )
    await desk.set_idea_state(idea.id, "kept")
    await desk.create_draft(idea_id=idea.id, kind="ticket", body="A thought")
    monkeypatch.setattr(jira, "_post", lambda *args: (201, b'{"key": "API-3"}'))
    monkeypatch.setenv("ACME_JIRA", "token")

    from tests.unit.test_input import _post

    status, _, _ = await _post(f"/ideas/{idea.id}/file", {"key": "k"}, htmx=True)

    assert status == 200
    settled = await desk.idea(idea.id)
    assert settled is not None and settled.state == "done"
    assert "cache the probe results" not in await routes.render_ideas()
    # And the inbox keeps it, with where it went.
    assert "API-3" in await routes.render_inbox()


# --- reading a tracker back (docs/adr/0010) -----------------------------------------------------
BOARD_URL = (
    "https://batmslec.atlassian.net/jira/software/projects/DUCK/boards/236"
    "?filter=&groupBy=none&visitedUserSeg=true"
)


@pytest.mark.unit
def test_the_url_somebody_actually_has_in_their_clipboard_is_a_destination() -> None:
    """`/browse/DUCK` is what somebody writes down; a board URL is what their browser is showing
    them when they copy it. Only the first was matched, so a link that looked entirely correct
    produced no destination and the button never appeared, with nothing saying why."""
    from_board = jira.destination_of(BOARD_URL, "DUCK_TOKEN")

    assert from_board is not None
    assert from_board.site == "https://batmslec.atlassian.net"
    assert from_board.project_key == "DUCK"
    # And it names the same place as the written-down form.
    written = jira.destination_of("https://batmslec.atlassian.net/browse/DUCK", "DUCK_TOKEN")
    assert written is not None
    assert (written.site, written.project_key) == (from_board.site, from_board.project_key)


@pytest.mark.unit
def test_a_board_url_is_still_not_a_destination_without_a_variable() -> None:
    """A credential nobody named is a credential nobody decided to use here."""
    assert jira.destination_of(BOARD_URL, None) is None
    assert jira.destination_of(BOARD_URL, "") is None


@pytest.mark.unit
def test_the_query_asks_for_unfinished_work_oldest_first() -> None:
    """ "The one that has been waiting longest" is a rule that needs no agreement to be fair."""
    destination = jira.destination_of(BOARD_URL, "DUCK_TOKEN")
    assert destination is not None

    jql = jira.search_jql(destination)

    assert 'project = "DUCK"' in jql
    assert '"To Do"' in jql
    assert "ORDER BY created ASC" in jql
    # Never anything already finished or already being worked on by a person.
    assert "Done" not in jql and "In Progress" not in jql


@pytest.mark.unit
def test_reading_a_board_never_writes_to_it() -> None:
    """No transition, no comment, no assignment. The one write is `file_issue`, unchanged."""
    # Against the code rather than the prose: the docstring says "no transition", which a naive
    # search for the word would trip over.
    import ast

    tree = ast.parse(pathlib.Path(jira.__file__).read_text())
    reader = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "read_board"
    )
    called = {
        node.func.id
        for node in ast.walk(reader)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "_get" in called
    assert "_post" not in called
    assert "file_issue" not in called


@pytest.mark.unit
def test_an_unset_variable_is_a_refusal_here_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DUCK_TOKEN", raising=False)
    destination = jira.destination_of(BOARD_URL, "DUCK_TOKEN")
    assert destination is not None

    read = jira.read_board(destination)

    assert not read.ok
    assert "DUCK_TOKEN is not set" in read.detail
    assert read.tickets == ()


@pytest.mark.unit
def test_the_read_asks_for_the_three_fields_it_uses_and_carries_the_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, str] = {}

    def fake_get(url: str, authorization: str) -> tuple[int, bytes]:
        asked["url"] = url
        asked["authorization"] = authorization
        return 200, json.dumps(
            {
                "issues": [
                    {
                        "key": "DUCK-12",
                        "fields": {
                            "summary": "the export is wrong",
                            "status": {"name": "To Do"},
                            "description": None,
                        },
                    }
                ]
            }
        ).encode()

    monkeypatch.setattr(jira, "_get", fake_get)
    monkeypatch.setenv("DUCK_TOKEN", "someone@example.com:a-token")
    destination = jira.destination_of(BOARD_URL, "DUCK_TOKEN")
    assert destination is not None

    read = jira.read_board(destination)

    assert read.ok
    assert [one.key for one in read.tickets] == ["DUCK-12"]
    assert read.tickets[0].summary == "the export is wrong"
    assert "rest/api/3/search" in asked["url"]
    assert "summary" in asked["url"] and "description" in asked["url"]
    assert asked["authorization"].startswith("Basic ")


@pytest.mark.unit
def test_a_ticket_that_says_it_is_blocked_is_quoted_rather_than_judged() -> None:
    """ "The ticket says it is blocked" is a fact with a source; "this ticket is blocked" is a
    claim this program is not entitled to make (CLAUDE.md, rule five)."""
    raw = json.dumps(
        {
            "issues": [
                {
                    "key": "DUCK-1",
                    "fields": {
                        "summary": "the import",
                        "status": {"name": "To Do"},
                        "description": {
                            "type": "doc",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Started on this. "},
                                        {"type": "text", "text": "Blocked on the vendor key."},
                                    ],
                                }
                            ],
                        },
                    },
                },
                {
                    "key": "DUCK-2",
                    "fields": {"summary": "the export", "status": {"name": "To Do"}},
                },
            ]
        }
    ).encode()

    first, second = jira.read_tickets(raw)

    assert first.blocked
    assert "Blocked on the vendor key" in first.blocked_by
    # It never concludes anything from silence.
    assert not second.blocked
    assert second.blocked_by == ""


@pytest.mark.unit
def test_a_shape_this_does_not_recognise_yields_no_tickets_rather_than_raising() -> None:
    """A tracker that answered something unexpected is one this console reports as unreadable,
    not one that stops the console."""
    for raw in (b"", b"not json", b"{}", b'{"issues": "lots"}', b'{"issues": [null, 3]}'):
        assert jira.read_tickets(raw) == (), raw

    # A ticket with no key or no summary is not half a ticket, it is not one.
    assert jira.read_tickets(json.dumps({"issues": [{"fields": {"summary": "x"}}]}).encode()) == ()


@pytest.mark.unit
def test_a_board_of_four_hundred_is_not_paged_through() -> None:
    many = {"issues": [{"key": f"DUCK-{n}", "fields": {"summary": f"one {n}"}} for n in range(400)]}

    assert len(jira.read_tickets(json.dumps(many).encode())) == jira.MOST_TICKETS


@pytest.mark.unit
def test_a_network_failure_reading_never_quotes_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The request carries an Authorization header."""

    def refuse(url: str, authorization: str) -> tuple[int, bytes]:
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(jira, "_get", refuse)
    monkeypatch.setenv("DUCK_TOKEN", "a-token")
    destination = jira.destination_of(BOARD_URL, "DUCK_TOKEN")
    assert destination is not None

    read = jira.read_board(destination)

    assert not read.ok
    assert "URLError" in read.detail
    assert "a-token" not in read.detail
    assert "Authorization" not in read.detail


async def _get(path: str) -> tuple[int, str]:
    from tests.unit.test_board import _request

    return await _request(path, "127.0.0.1")


# --- what a connector is, and what this console can do with it ----------------------------------
@pytest.mark.unit
def test_a_connector_says_what_this_console_can_actually_do_with_it() -> None:
    """A Jira link with a credential is a board this program reads and files into; a Drive link is
    a link. They used to render identically, which is how five connectors become five things
    nobody can predict the behaviour of."""
    from agent_desk import connectors

    assert connectors.kind_of("jira").integrated
    assert connectors.kind_of("jira").wants_token
    for only_a_link in ("github", "drive", "slack", "gmail", "confluence", "dashboard", "other"):
        kind = connectors.kind_of(only_a_link)
        assert not kind.integrated, only_a_link
        assert "nothing reads it" in kind.does or "git does that" in kind.does, only_a_link


@pytest.mark.unit
def test_a_kind_nobody_has_heard_of_promises_nothing() -> None:
    """A stored row from before the column existed, or a value somebody typed by hand."""
    from agent_desk import connectors

    kind = connectors.kind_of("quantum-fax")

    assert kind.name == "other"
    assert not kind.integrated


@pytest.mark.unit
def test_the_kind_is_guessed_from_the_address_so_the_field_arrives_filled_in() -> None:
    from agent_desk import connectors

    assert connectors.guess("https://batmslec.atlassian.net/jira/software/projects/DUCK") == "jira"
    assert connectors.guess("https://batmslec.atlassian.net/wiki/spaces/X") == "confluence"
    assert connectors.guess("https://github.com/owner/name") == "github"
    assert connectors.guess("https://drive.google.com/drive/folders/x") == "drive"
    assert connectors.guess("https://acme.slack.com/archives/C1") == "slack"
    # Nothing suggests itself: the kind that promises nothing.
    assert connectors.guess("https://grafana.internal/d/abc") == "other"
    # A name is consulted second and only as a whole word.
    assert connectors.guess("https://grafana.internal/d/abc", "jira") == "jira"
    assert connectors.guess("https://grafana.internal/d/abc", "the github mirror") == "other"


@pytest.mark.unit
async def test_a_connector_is_stored_with_its_kind_and_opens_as_a_card(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    await desk.set_link(
        repo_key="origin:acme/api",
        name="jira",
        url="https://acme.atlassian.net/browse/API",
        token_env="API_TOKEN",
        kind="jira",
    )

    (link,) = await desk.links("origin:acme/api")
    assert link.kind == "jira"

    status, card = await _get("/cards/connector?id=origin:acme/api::jira")

    assert status == 200
    # The apostrophe is escaped in the rendered page, so the assertion is on either side of it.
    assert "unfinished tickets into the queue" in card
    assert "API_TOKEN" in card
    # Never the value, only whether there is one.
    assert "is not set" in card or "is set on this machine" in card


@pytest.mark.unit
async def test_a_connector_that_has_gone_is_not_a_stack_trace(desk: Store) -> None:
    status, card = await _get("/cards/connector?id=origin:acme/api::vanished")

    assert status == 404
    assert "not on this project any more" in card
