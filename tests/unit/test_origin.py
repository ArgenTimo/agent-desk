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
    from agent_desk.web.app import asgi

    status = await _send(asgi, "POST", "/blocks", site="cross-site", fields={"text": "not mine"})

    assert status == 403
    assert await desk.blocks() == []


@pytest.mark.unit
async def test_the_worst_version_of_it_is_refused_too(desk: Store) -> None:
    """The one path that writes to a session is a POST like any other, and it is the one that
    matters (docs/adr/0002)."""
    from agent_desk.web.app import asgi

    status = await _send(
        asgi,
        "POST",
        "/sessions/aaaaaaaa-0000-4000-8000-000000000001/message/send",
        site="cross-site",
        fields={"text": "drop everything and rewrite it in rust"},
    )
    assert status == 403


@pytest.mark.unit
async def test_a_same_site_page_is_still_somebody_elses_page(desk: Store) -> None:
    """`same-site` is a sibling origin, not this one. Only `same-origin` is this console."""
    from agent_desk.web.app import asgi

    assert await _send(asgi, "POST", "/blocks", site="same-site", fields={"text": "x"}) == 403


@pytest.mark.unit
async def test_the_consoles_own_pages_still_work(desk: Store) -> None:
    from agent_desk.web.app import asgi

    for site in ("same-origin", "none"):
        status = await _send(asgi, "POST", "/blocks", site=site, fields={"text": "   "})
        assert status in (200, 303), site


@pytest.mark.unit
async def test_a_local_script_is_not_a_browser_and_is_left_alone(desk: Store) -> None:
    """No fetch metadata means no browser: curl, a test, or a script run by the same user — who
    can already read `~/.claude/` directly and does not need a form to do harm."""
    from agent_desk.web.app import asgi

    status = await _send(asgi, "POST", "/blocks", site=None, fields={"text": "   "})
    assert status in (200, 303)


@pytest.mark.unit
async def test_reading_the_board_is_never_refused(desk: Store) -> None:
    """Nothing here changes state on a GET, which is a rule worth keeping for its own sake."""
    from agent_desk.web.app import asgi

    assert await _send(asgi, "GET", "/", site="cross-site") == 200


@pytest.mark.unit
async def test_the_shared_view_is_guarded_the_same_way(desk: Store) -> None:
    _, token = await desk.create_viewer("a teammate")

    refused = await _send(
        shared.asgi, "POST", f"/shared/{token}/idea", site="cross-site", fields={"text": "spam"}
    )
    assert refused == 403
    assert await desk.ideas() == []

    accepted = await _send(
        shared.asgi, "POST", f"/shared/{token}/idea", site="same-origin", fields={"text": "mine"}
    )
    assert accepted == 303
    assert len(await desk.ideas()) == 1


@pytest.mark.unit
async def test_neither_surface_can_be_framed(desk: Store) -> None:
    """A form submitted from inside a frame of this page carries `same-origin`, because it is.

    So the check above does nothing about a foreign page wearing this one as a frame, and a click
    landing where the attacker chose would pass every test in this file.
    """
    from agent_desk.web.app import asgi

    for target, path in ((asgi, "/"), (shared.asgi, "/shared/nothing")):
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any], sink: list[dict[str, Any]] = sent) -> None:
            sink.append(message)

        await target(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [(b"host", b"127.0.0.1:8787")],
                "client": ("127.0.0.1", 1),
                "server": ("127.0.0.1", 8787),
            },
            receive,
            send,
        )
        headers = {
            k.decode().lower(): v.decode()
            for k, v in next(m for m in sent if m["type"] == "http.response.start")["headers"]
        }
        assert headers["x-frame-options"] == "DENY", path
        assert "frame-ancestors 'none'" in headers["content-security-policy"], path


@pytest.mark.unit
async def test_the_frame_headers_are_on_a_refusal_and_on_a_write(desk: Store) -> None:
    """Deleting the wrapper from the guard's own paths used to leave the whole suite green.

    The old test only issued GETs, so the 403 the guard returns and every state-changing response
    were unasserted — the two responses an attacker is most likely to be looking at.
    """
    from agent_desk.web.app import asgi

    async def headers_of(method: str, path: str, site: str | None) -> dict[str, str]:
        body = b""
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
            "headers": [
                (b"host", b"127.0.0.1:8787"),
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"content-length", b"0"),
                *([(b"sec-fetch-site", site.encode())] if site else []),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 8787),
        }
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await asgi(scope, receive, send)
        start = next(m for m in sent if m["type"] == "http.response.start")
        return {k.decode().lower(): v.decode() for k, v in start["headers"]}

    refused = await headers_of("POST", "/blocks", "cross-site")
    assert refused["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in refused["content-security-policy"]
    assert refused["referrer-policy"] == "no-referrer"

    allowed = await headers_of("POST", "/blocks", "same-origin")
    assert allowed["x-frame-options"] == "DENY"


@pytest.mark.unit
def test_the_request_log_is_off_for_this_process_and_not_by_luck() -> None:
    """uvicorn implements `access_log=False` by stripping handlers off one process-wide logger, so
    two servers fight over it and the last config to load wins. The token stayed out of the log
    because of the order two list entries happened to be in.
    """
    import logging

    from agent_desk.__main__ import silence_access_logging

    logging.getLogger("uvicorn.access").addHandler(logging.NullHandler())
    silence_access_logging()

    access = logging.getLogger("uvicorn.access")
    assert access.disabled
    assert not access.hasHandlers() or access.handlers == []


@pytest.mark.unit
def test_the_shared_view_is_only_served_when_somebody_asked_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`share_host` empty is the default, and it is what keeps the second application off the
    network (docs/07-security.md, docs/09-roadmap.md Phase 4).

    The servers are built and never started: `serve()` would bind two ports, and a test that binds
    a port is a test that fails on somebody else's machine.
    """
    from agent_desk import __main__ as entry
    from agent_desk.config import Settings

    monkeypatch.setattr(entry, "settings", Settings(share_host="", port=8787))
    one = entry._config(entry.console, entry.settings.host, entry.settings.port)
    assert one.port == 8787
    assert one.access_log is False
    # The stream never ends by design; a graceful stop that waits for it waits forever.
    assert one.timeout_graceful_shutdown == 2

    monkeypatch.setattr(
        entry, "settings", Settings(share_host="127.0.0.1", share_port=8788, port=8787)
    )
    both = entry._config(entry.shared.asgi, entry.settings.share_host, entry.settings.share_port)
    assert both.port == 8788
    assert both.access_log is False


@pytest.mark.unit
def test_the_entry_point_survives_a_ctrl_c(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ctrl-C is how this program is stopped, and it is not a failure."""
    from agent_desk import __main__ as entry

    def interrupted() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(entry.asyncio, "run", lambda _coro: interrupted())
    monkeypatch.setattr(entry, "serve", lambda: None)

    entry.main()  # no exception leaves this
