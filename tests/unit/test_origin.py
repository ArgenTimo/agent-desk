"""A page you happen to be visiting must not be able to act on your console.

The console binds to loopback and checks `Host`, and neither stops a cross-site form post: forms
do not ask CORS for permission, and the request carries the right `Host` because it really is
going there. What stops it is the fetch metadata a browser attaches and a page cannot forge.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

import pytest
from agent_desk.store.repo import Store
from agent_desk.web import routes, shared


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    shared.app.state.store = store
    yield store
    await store.close()
    shared.app.state.store = None


async def _send(
    app: Any, method: str, path: str, *, site: str | None, fields: dict[str, str] | None = None
) -> int:
    body = urlencode(fields or {}).encode()
    headers = [
        (b"host", b"127.0.0.1:8787"),
        (b"content-type", b"application/x-www-form-urlencoded"),
        (b"content-length", str(len(body)).encode()),
    ]
    if site is not None:
        headers.append((b"sec-fetch-site", site.encode()))

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 54321),
        "server": ("127.0.0.1", 8787),
    }
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return int(next(m for m in sent if m["type"] == "http.response.start")["status"])


@pytest.mark.unit
async def test_a_foreign_page_cannot_ask_a_question_through_your_console(desk: Store) -> None:
    """The cheapest version of the attack: a form on any website, submitted by your browser."""
    from agent_desk.web.app import app

    status = await _send(app, "POST", "/blocks", site="cross-site", fields={"text": "not mine"})

    assert status == 403
    assert await desk.blocks() == []


@pytest.mark.unit
async def test_the_worst_version_of_it_is_refused_too(desk: Store) -> None:
    """The one path that writes to a session is a POST like any other, and it is the one that
    matters (docs/adr/0002)."""
    from agent_desk.web.app import app

    status = await _send(
        app,
        "POST",
        "/sessions/aaaaaaaa-0000-4000-8000-000000000001/message/send",
        site="cross-site",
        fields={"text": "drop everything and rewrite it in rust"},
    )
    assert status == 403


@pytest.mark.unit
async def test_a_same_site_page_is_still_somebody_elses_page(desk: Store) -> None:
    """`same-site` is a sibling origin, not this one. Only `same-origin` is this console."""
    from agent_desk.web.app import app

    assert await _send(app, "POST", "/blocks", site="same-site", fields={"text": "x"}) == 403


@pytest.mark.unit
async def test_the_consoles_own_pages_still_work(desk: Store) -> None:
    from agent_desk.web.app import app

    for site in ("same-origin", "none"):
        status = await _send(app, "POST", "/blocks", site=site, fields={"text": "   "})
        assert status in (200, 303), site


@pytest.mark.unit
async def test_a_local_script_is_not_a_browser_and_is_left_alone(desk: Store) -> None:
    """No fetch metadata means no browser: curl, a test, or a script run by the same user — who
    can already read `~/.claude/` directly and does not need a form to do harm."""
    from agent_desk.web.app import app

    status = await _send(app, "POST", "/blocks", site=None, fields={"text": "   "})
    assert status in (200, 303)


@pytest.mark.unit
async def test_reading_the_board_is_never_refused(desk: Store) -> None:
    """Nothing here changes state on a GET, which is a rule worth keeping for its own sake."""
    from agent_desk.web.app import app

    assert await _send(app, "GET", "/", site="cross-site") == 200


@pytest.mark.unit
async def test_the_shared_view_is_guarded_the_same_way(desk: Store) -> None:
    _, token = await desk.create_viewer("a teammate")

    refused = await _send(
        shared.app, "POST", f"/shared/{token}/idea", site="cross-site", fields={"text": "spam"}
    )
    assert refused == 403
    assert await desk.ideas() == []

    accepted = await _send(
        shared.app, "POST", f"/shared/{token}/idea", site="same-origin", fields={"text": "mine"}
    )
    assert accepted == 303
    assert len(await desk.ideas()) == 1
