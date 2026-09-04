"""The shared view: the surface a second person can open.

docs/07-security.md calls this the point at which every other sentence in it stops being
sufficient, so these tests are about the four decisions that hold it down rather than about the
page rendering. Three of them are structural, and a structural rule is worth a test precisely
because nobody will remember it on a hurried afternoon.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

import pytest
from agent_desk.store.repo import Store, token_hash
from agent_desk.web import shared

SHARED_SOURCE = pathlib.Path(shared.__file__)


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    shared.app.state.store = store
    yield store
    await store.close()
    shared.app.state.store = None


async def _request(
    method: str, path: str, fields: dict[str, str] | None = None
) -> tuple[int, str, dict[str, str]]:
    """Drive the shared application itself — not the console, which is a different app."""
    body = urlencode(fields or {}).encode()
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
            (b"host", b"desk.example:8788"),
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"content-length", str(len(body)).encode()),
        ],
        # A viewer on the network, reaching a console bound to one interface rather than to all
        # of them — which is what `make share SHARE_HOST=…` is for.
        "client": ("192.168.1.50", 41234),
        "server": ("192.168.1.10", 8788),
    }
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await shared.asgi(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    html = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    headers = {k.decode(): v.decode() for k, v in start.get("headers", [])}
    return int(start["status"]), html.decode(), headers


# --- the surfaces are separate ----------------------------------------------------------------
@pytest.mark.unit
def test_the_shared_view_cannot_reach_the_board_or_the_write_path() -> None:
    """The separation is structural, not a conditional that can be got wrong.

    A single application deciding per request whether a viewer may see the board would work, and
    it would be one bad branch away from not working. This one has no way to reach either.
    """
    tree = ast.parse(SHARED_SOURCE.read_text())
    imported = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
        )
    }

    assert not any("peer" in name for name in imported), "the shared view must not reach a session"
    assert not any("observe" in name for name in imported), "the shared view must not see the board"
    assert not any(name.endswith("routes") for name in imported), "it is its own application"


@pytest.mark.unit
def test_it_owns_no_store_and_opens_none() -> None:
    """The console's lifespan owns the one connection; this application borrows it."""
    source = SHARED_SOURCE.read_text()
    assert "Store(" not in source.replace("Store | None", "").replace("-> Store", "")
    assert ".open()" not in source
    assert ".close()" not in source


@pytest.mark.unit
def test_its_templates_cannot_include_an_owner_fragment() -> None:
    """A separate loader rooted in a separate directory: unreachable, not merely unused."""
    assert shared.TEMPLATES.name == "shared"
    assert {p.name for p in shared.TEMPLATES.glob("*.html")} == {"page.html", "gone.html"}


# --- the link is the identity ------------------------------------------------------------------
@pytest.mark.unit
async def test_a_link_names_one_person_and_only_its_hash_is_kept(desk: Store) -> None:
    viewer, token = await desk.create_viewer("Dasha from design")

    assert viewer.name == "Dasha from design"
    assert viewer.active
    assert len(token) > 40
    async with desk.engine.connect() as conn:
        from sqlalchemy import text

        rows = await conn.execute(text("SELECT token_hash FROM viewer"))
        stored = [row[0] for row in rows]
    # The token itself is not in the file, so this file leaking is not the links leaking.
    assert stored == [token_hash(token)]
    assert token not in stored[0]


@pytest.mark.unit
async def test_a_revoked_link_stops_opening_anything(desk: Store) -> None:
    viewer, token = await desk.create_viewer("a former teammate")
    status, _, _ = await _request("GET", f"/shared/{token}")
    assert status == 200

    await desk.revoke_viewer(viewer.id)
    status, html, _ = await _request("GET", f"/shared/{token}")
    assert status == 404
    assert "does not open anything" in html

    # Revocation is a timestamp, because an audit asks "until when", not "was there one".
    revoked = next(v for v in await desk.viewers() if v.id == viewer.id)
    assert revoked.revoked_at is not None
    assert revoked.name == "a former teammate"


@pytest.mark.unit
async def test_a_wrong_link_and_a_revoked_one_are_indistinguishable(desk: Store) -> None:
    """A viewer learns whether their own link works, and nothing else."""
    viewer, token = await desk.create_viewer("someone")
    await desk.revoke_viewer(viewer.id)

    _, revoked_html, _ = await _request("GET", f"/shared/{token}")
    _, nonsense_html, _ = await _request("GET", "/shared/not-a-token-at-all")
    assert revoked_html == nonsense_html


# --- what it shows, and what it does not -------------------------------------------------------
@pytest.mark.unit
async def test_it_shows_the_thought_and_nothing_around_it(desk: Store) -> None:
    """The disclosure decision of docs/07-security.md, asserted field by field.

    The context is what makes an idea legible to its owner a week later, and it is also a list of
    what that person was working on. A teammate gets the thought.
    """
    _, token = await desk.create_viewer("a teammate")
    await desk.create_idea(
        text_="cache the probe results per project",
        summary="Cache tracker probes",
        source_kind="session",
        source_ref="00000000-0000-4000-8000-000000000001",
        context={
            "project": "llm-developer-2",
            "branch": "boba/duck-129-secret-name",
            "title": "Docker client for the supervisor",
        },
    )
    idea = (await desk.ideas())[0]
    await desk.create_draft(idea_id=idea.id, kind="proposal", body="it quotes docs/03 and paths")

    status, html, _ = await _request("GET", f"/shared/{token}")

    assert status == 200
    assert "Cache tracker probes" in html
    assert "cache the probe results per project" in html
    for hidden in (
        "llm-developer-2",
        "boba/duck-129-secret-name",
        "Docker client for the supervisor",
        "00000000-0000-4000-8000-000000000001",
        "it quotes docs/03 and paths",
    ):
        assert hidden not in html, f"the shared view disclosed {hidden!r}"


@pytest.mark.unit
async def test_a_question_typed_into_the_console_is_never_on_this_page(desk: Store) -> None:
    """Blocks live in the same file and are not part of this surface at all."""
    _, token = await desk.create_viewer("a teammate")
    thread = await desk.create_thread("a subject")
    await desk.create_block(
        thread_id=thread.id,
        kind="question",
        input="what did the client do about the customer's timeout",
        thread_set_by="human",
    )

    _, html, _ = await _request("GET", f"/shared/{token}")
    assert "customer's timeout" not in html


@pytest.mark.unit
async def test_everything_it_renders_is_scrubbed(desk: Store) -> None:
    """The owner's own copy stays verbatim; a second person gets the filtered version.

    The store keeps a human's words untouched on purpose (docs/05-ideas.md). "Any surface a second
    person can open redacts before it renders" is about this page (docs/07-security.md).
    """
    _, token = await desk.create_viewer("a teammate")
    secret = "ghp_" + "q" * 36
    await desk.create_idea(
        text_=f"the deploy key {secret} should be rotated", summary="rotate it", source_kind="typed"
    )

    _, html, _ = await _request("GET", f"/shared/{token}")
    assert secret not in html
    assert "[redacted]" in html
    # And the owner still has what they wrote.
    assert secret in (await desk.ideas())[0].text


@pytest.mark.unit
async def test_the_page_carries_no_javascript(desk: Store) -> None:
    """The person opening it is on an unknown device and is not here to debug a console."""
    _, token = await desk.create_viewer("a teammate")
    _, html, _ = await _request("GET", f"/shared/{token}")

    assert "<script" not in html
    assert "onclick" not in html


# --- the other half of problem 5 ---------------------------------------------------------------
@pytest.mark.unit
async def test_a_teammate_can_add_an_idea_and_it_is_attributed(desk: Store) -> None:
    """docs/01-vision.md problem 5 is "contribute ideas *and* see progress"."""
    _, token = await desk.create_viewer("Dasha from design")

    status, _, headers = await _request(
        "POST", f"/shared/{token}/idea", {"text": "the board should have a dark mode"}
    )

    # A redirect, so a refresh does not submit it again.
    assert status == 303
    assert headers["location"] == f"/shared/{token}"

    (idea,) = await desk.ideas()
    assert idea.text == "the board should have a dark mode"
    assert idea.state == "new"
    # An idea whose author is unknown is an idea nobody can ask about.
    assert idea.context["from"] == "Dasha from design"


@pytest.mark.unit
async def test_an_unknown_link_cannot_write_anything(desk: Store) -> None:
    status, _, _ = await _request("POST", "/shared/not-a-token/idea", {"text": "spam"})

    assert status == 404
    assert await desk.ideas() == []


@pytest.mark.unit
async def test_an_empty_submission_writes_nothing(desk: Store) -> None:
    _, token = await desk.create_viewer("a teammate")
    status, _, _ = await _request("POST", f"/shared/{token}/idea", {"text": "   "})

    assert status == 303
    assert await desk.ideas() == []


# --- the bind that changes the model ------------------------------------------------------------
@pytest.mark.unit
def test_the_shared_view_is_not_served_unless_someone_says_so() -> None:
    """The default is the state this tool spends most of its life in: not shared at all.

    `share_host` empty means the second application is never even constructed, so the loopback
    argument of docs/07-security.md still covers everything until a human types the sentence that
    changes it (`make share SHARE_HOST=…`).
    """
    from agent_desk.config import Settings

    assert Settings().share_host == ""

    source = pathlib.Path(shared.__file__).parent.parent / "__main__.py"
    body = source.read_text()
    assert "if settings.share_host:" in body


@pytest.mark.unit
def test_the_console_and_the_shared_view_are_two_applications() -> None:
    """Two binds, one process (docs/adr/0003 keeps the second half of that)."""
    from agent_desk.web.app import app as console

    assert shared.app is not console
    assert {route.path for route in shared.app.routes} >= {
        "/shared/{token}",
        "/shared/{token}/idea",
    }
    # Nothing the console serves is reachable here.
    shared_paths = {getattr(route, "path", "") for route in shared.app.routes}
    for owner_path in ("/", "/blocks", "/ideas", "/viewers", "/events"):
        assert owner_path not in shared_paths


# --- what a reviewer found by mutating this file ------------------------------------------------
@pytest.mark.unit
async def test_two_links_are_not_the_same_link(desk: Store) -> None:
    """A reviewer replaced `new_token()` with fifty letter As and the whole suite stayed green.

    The link is the entire security model — no accounts, no second factor, no TLS — and the only
    assertions on it were its length and that its hash is its hash.
    """
    import re

    _, first = await desk.create_viewer("one")
    _, second = await desk.create_viewer("two")

    assert first != second
    for token in (first, second):
        assert len(token) >= 43, "256 bits of urlsafe base64 is 43 characters"
        assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
        # Not a constant, not a counter, not a name: enough distinct characters that a guess is
        # not a plan (docs/07-security.md).
        assert len(set(token)) > 16, token


@pytest.mark.unit
async def test_the_summary_is_scrubbed_as_well_as_the_text(desk: Store) -> None:
    """`fallback_summary` takes the idea's first non-blank line verbatim, so a secret on line one
    *is* the summary. The old test planted its secret only in the text and passed either way."""
    _, token = await desk.create_viewer("a teammate")
    secret = "ghp_" + "s" * 36
    await desk.create_idea(text_="a thought", summary=f"rotate {secret} first", source_kind="typed")

    _, html, _ = await _request("GET", f"/shared/{token}")
    assert secret not in html
    assert "[redacted]" in html


@pytest.mark.unit
async def test_the_page_says_when_each_idea_arrived(desk: Store) -> None:
    """Three documents promise the date and the page rendered everything but."""
    _, token = await desk.create_viewer("a teammate")
    await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")

    _, html, _ = await _request("GET", f"/shared/{token}")
    (idea,) = await desk.ideas()
    from agent_desk.web.shared import _when

    assert _when(idea.created_at) in html


@pytest.mark.unit
async def test_the_state_of_each_idea_is_on_the_page(desk: Store) -> None:
    """ "What happened to the ideas already there" is the half of problem 5 this page answers."""
    _, token = await desk.create_viewer("a teammate")
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    await desk.set_idea_state(idea.id, "promoted")

    _, html, _ = await _request("GET", f"/shared/{token}")
    assert "promoted" in html


@pytest.mark.unit
async def test_a_console_that_is_not_open_yet_answers_like_a_wrong_link(
    tmp_path: pathlib.Path,
) -> None:
    """Both servers start together, so there is a window at every start — and one at every stop.

    A viewer arriving in it used to get a RuntimeError out of a route whose whole promise is that
    everything it cannot serve looks the same.
    """
    shared.app.state.store = Store(tmp_path / "not-open.db")
    try:
        status, html, _ = await _request("GET", "/shared/any-token-at-all")
        assert status == 404
        assert "does not open anything" in html
    finally:
        shared.app.state.store = None


@pytest.mark.unit
async def test_a_link_holder_cannot_post_an_idea_of_any_size(desk: Store) -> None:
    """Authenticated is not the same as trusted with the owner's memory and disk."""
    _, token = await desk.create_viewer("a teammate")

    status, _, _ = await _request(
        "POST", f"/shared/{token}/idea", fields={"text": "x" * (shared.MAX_SUBMISSION_BYTES + 1)}
    )

    assert status == 413
    assert await desk.ideas() == []


# --- what the confirmation round found in the fixes ---------------------------------------------
async def _chunked(path: str, body: bytes, token_headers: bool = True) -> int:
    """A POST that declares no length, the way chunked encoding does not.

    The first version of the size cap read `Content-Length` and the test that covered it sent an
    honest one — a test that passed against a broken implementation. 128 KB went through with a
    303 and was stored whole.
    """
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"desk.example:8788"),
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"transfer-encoding", b"chunked"),
        ],
        "client": ("192.168.1.50", 41234),
        "server": ("192.168.1.10", 8788),
    }
    pieces = [body[i : i + 8192] for i in range(0, len(body), 8192)]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        if pieces:
            return {"type": "http.request", "body": pieces.pop(0), "more_body": bool(pieces)}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await shared.asgi(scope, receive, send)
    return int(next(m for m in sent if m["type"] == "http.response.start")["status"])


@pytest.mark.unit
async def test_a_body_with_no_declared_length_is_bounded_too(desk: Store) -> None:
    _, token = await desk.create_viewer("a teammate")
    huge = b"text=" + b"x" * (shared.MAX_SUBMISSION_BYTES * 8)

    assert await _chunked(f"/shared/{token}/idea", huge) == 413
    assert await desk.ideas() == []


@pytest.mark.unit
async def test_a_small_chunked_body_still_works(desk: Store) -> None:
    """The cap counts; it does not refuse everything that declines to declare itself."""
    _, token = await desk.create_viewer("a teammate")

    assert await _chunked(f"/shared/{token}/idea", b"text=a+small+thought") == 303
    (idea,) = await desk.ideas()
    assert idea.text == "a small thought"


@pytest.mark.unit
async def test_a_stray_byte_in_a_header_is_not_a_way_to_crash_the_process(desk: Store) -> None:
    """The guard runs before authentication, so this needed no token at all.

    Decoding every header as UTF-8 to read one of them made `X-Junk: \\xff` an unauthenticated
    remote 500 on the network bind, with a traceback per hit.
    """
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/shared/whatever/idea",
        "raw_path": b"/shared/whatever/idea",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"desk.example:8788"),
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"content-length", b"9"),
            (b"x-junk", b"\xff\xfe"),
        ],
        "client": ("192.168.1.50", 41234),
        "server": ("192.168.1.10", 8788),
    }
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"text=hmm", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await shared.asgi(scope, receive, send)
    status = int(next(m for m in sent if m["type"] == "http.response.start")["status"])
    assert status == 404, "a wrong token, answered without raising"


@pytest.mark.unit
async def test_the_store_closing_mid_request_answers_like_a_wrong_link(
    tmp_path: pathlib.Path,
) -> None:
    """The shutdown half of the window: the check passes, then `close()` lands at the await."""
    store = Store(tmp_path / "closing.db")
    await store.open()
    _, token = await store.create_viewer("a teammate")
    shared.app.state.store = store
    try:
        await store.close()
        status, html, _ = await _request("GET", f"/shared/{token}")
        assert status == 404
        assert "does not open anything" in html
    finally:
        shared.app.state.store = None


@pytest.mark.unit
async def test_the_token_comes_from_the_system_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Length, alphabet and spread all hold for a seeded PRNG, which is why they are not enough.

    A reviewer replaced `secrets.token_urlsafe` with `random.Random(seed)` over the same alphabet —
    entirely predictable — and the suite stayed green. The source is the property.
    """
    from agent_desk.store import repo

    asked: list[int] = []
    real = repo.secrets.token_urlsafe

    def watched(nbytes: int | None = None) -> str:
        asked.append(nbytes or 0)
        return real(nbytes)

    monkeypatch.setattr(repo.secrets, "token_urlsafe", watched)
    token = repo.new_token()

    assert asked == [32], "256 bits, from `secrets`, and from nowhere else"
    assert len(token) >= 43
