"""The one door out to a tracker, and everything it refuses to do (docs/adr/0005).

The transport is replaced here rather than mocked at the library level: what is worth asserting is
the request this program would make, and the ways it declines to make one at all.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import secrets as kept
from agent_desk.config import Settings
from agent_desk.store.repo import Store
from agent_desk.tracker import jira
from agent_desk.web import routes

SITE = "https://acme.atlassian.net"


@pytest.fixture
def nowhere(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine with no secret of its own, so a test never reads the developer's.

    `file_issue` looks in the shell and in this machine's secret file, and the second is a real
    path under the home directory of whoever runs the suite (agent_desk/secrets.py).
    """
    monkeypatch.setattr(kept, "settings", Settings(data_dir=tmp_path / "data"))


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
    nowhere: None,
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
def test_a_token_typed_into_the_console_is_the_one_the_request_carries(
    nowhere: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/07-security.md: a token may be typed into the console, and it stays on this machine.

    The project card reads `secrets.has`, so it says *set here* for a token that was never
    exported. Filing read `os.environ` alone and refused it — the console reporting a credential
    that the one path it exists for could not see.
    """
    monkeypatch.delenv("ACME_JIRA", raising=False)
    kept.keep("ACME_JIRA", "typed-into-the-console")

    seen: dict[str, object] = {}

    def fake_post(url: str, body: bytes, authorization: str) -> tuple[int, bytes]:
        seen["authorization"] = authorization
        return 201, b'{"key": "API-7"}'

    monkeypatch.setattr(jira, "_post", fake_post)

    result = jira.file_issue(jira.Destination(SITE, "API", "ACME_JIRA"), "one", "two")

    assert result.filed
    assert seen["authorization"] == "Bearer typed-into-the-console"


@pytest.mark.unit
def test_the_shell_still_wins_over_what_was_typed_months_ago(
    nowhere: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator with a secret manager is not quietly shadowed by a browser."""
    kept.keep("ACME_JIRA", "typed-into-the-console")
    monkeypatch.setenv("ACME_JIRA", "exported-in-the-shell")

    seen: dict[str, object] = {}

    def fake_post(url: str, body: bytes, authorization: str) -> tuple[int, bytes]:
        seen["authorization"] = authorization
        return 201, b'{"key": "API-8"}'

    monkeypatch.setattr(jira, "_post", fake_post)

    assert jira.file_issue(jira.Destination(SITE, "API", "ACME_JIRA"), "one", "two").filed
    assert seen["authorization"] == "Bearer exported-in-the-shell"


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
