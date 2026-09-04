"""The board, assembled from a fake `~/.claude` and rendered.

The registry entries here are alive in the only sense the reader accepts: they name this test
process and its parent, and they carry the `procStart` the kernel reports for them. That is the
liveness check of docs/03-session-observation.md running for real rather than being stubbed out.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from agent_desk.config import Settings
from agent_desk.observe import registry, transcript
from agent_desk.store.repo import Store
from agent_desk.web import routes, sse
from jinja2 import UndefinedError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MINUTE = 60_000

pytestmark = pytest.mark.skipif(
    not Path("/proc/self/stat").exists(),
    reason="liveness is /proc-based; docs/03-session-observation.md was verified on Linux",
)


def _starttime(pid: int) -> str:
    stat = Path(f"/proc/{pid}/stat").read_text()
    return stat[stat.rfind(")") + 1 :].split()[22 - 3]


class Home:
    """A fake `~/.claude`: the registry and the transcripts, and nothing else in it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "sessions").mkdir(parents=True)
        (root / "projects").mkdir(parents=True)

    def session(self, pid: int, session_id: str, **overrides: Any) -> dict[str, Any]:
        entry: dict[str, Any] = json.loads((FIXTURES / "registry_entry.json").read_text())
        entry.update(pid=pid, procStart=_starttime(pid), sessionId=session_id, **overrides)
        (self.root / "sessions" / f"{pid}.json").write_text(json.dumps(entry))
        return entry

    def transcript(self, session_id: str, *lines: dict[str, Any], slug: str = "-somewhere") -> None:
        directory = self.root / "projects" / slug
        directory.mkdir(exist_ok=True)
        (directory / f"{session_id}.jsonl").write_text(
            "".join(json.dumps(line) + "\n" for line in lines)
        )


def _entry(role: str, text: str, branch: str = "main") -> dict[str, Any]:
    return {
        "type": role,
        "isSidechain": False,
        "gitBranch": branch,
        "timestamp": "2026-09-02T14:05:19.000Z",
        "message": {"role": role, "content": [{"type": "text", "text": text}]},
    }


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Home:
    """Point every module that resolves a path at the fake tree, and poll without waiting."""
    fake = Settings(
        claude_home=tmp_path / "claude",
        data_dir=tmp_path / "data",
        registry_poll_seconds=0.0,
        idle_hint_seconds=300,
    )
    for module in (registry, transcript, routes, sse):
        monkeypatch.setattr(module, "settings", fake)
    return Home(tmp_path / "claude")


@pytest.mark.unit
def test_one_page_answers_what_every_agent_is_doing(home: Home) -> None:
    """docs/01-vision.md, problems 1 and 4: project, branch, status, title, asked, did."""
    now = int(time.time() * 1000)
    home.session(
        os.getpid(),
        "aaaaaaaa-0000-4000-8000-000000000001",
        cwd="/home/dev/projects/alpha",
        status="busy",
        updatedAt=now,
        statusUpdatedAt=now,
    )
    home.transcript(
        "aaaaaaaa-0000-4000-8000-000000000001",
        {"type": "ai-title", "aiTitle": "Docker client for the supervisor"},
        {"type": "last-prompt", "lastPrompt": "what about timeouts"},
        _entry("user", "what about timeouts", branch="boba/duck-129"),
        _entry("assistant", "reading the client", branch="boba/duck-129"),
    )

    html = routes.render_board()
    assert "alpha" in html
    assert "boba/duck-129" in html
    assert "busy" in html
    assert "Docker client for the supervisor" in html
    assert "what about timeouts" in html
    assert "reading the client" in html


@pytest.mark.unit
def test_the_session_that_may_be_waiting_sorts_above_the_one_that_is_working(home: Home) -> None:
    now = int(time.time() * 1000)
    home.session(
        os.getpid(),
        "aaaaaaaa-0000-4000-8000-000000000001",
        cwd="/home/dev/projects/alpha",
        status="busy",
        updatedAt=now,
        statusUpdatedAt=now,
    )
    home.transcript("aaaaaaaa-0000-4000-8000-000000000001", _entry("assistant", "working"))
    home.session(
        os.getppid(),
        "bbbbbbbb-0000-4000-8000-000000000002",
        cwd="/home/dev/projects/beta",
        status="idle",
        updatedAt=now - 14 * MINUTE,
        statusUpdatedAt=now - 14 * MINUTE,
    )
    home.transcript(
        "bbbbbbbb-0000-4000-8000-000000000002", _entry("assistant", "done, over to you")
    )

    html = routes.render_board()
    # Sorted by what the human is deciding, not by updatedAt — which would put alpha first.
    assert html.index("beta") < html.index("alpha")
    assert "may be waiting for you" in html
    assert "idle 14m · last entry: assistant" in html
    assert "guess" in html
    # The class the stylesheet colours and the script counts for the window title. It lives in
    # three files and nothing else would notice them drifting apart.
    assert re.search(r'class="row [a-z]+ flagged"', html)


@pytest.mark.unit
def test_a_session_with_no_transcript_says_so_rather_than_guessing(home: Home) -> None:
    """docs/02-architecture.md, failure posture: registry facts only, marked as such."""
    home.session(os.getpid(), "cccccccc-0000-4000-8000-000000000003")
    html = routes.render_board()
    assert "registry facts only" in html


@pytest.mark.unit
def test_an_empty_registry_is_an_empty_board(home: Home) -> None:
    assert "No live sessions" in routes.render_board()


@pytest.mark.unit
def test_a_dead_entry_leaves_the_board_empty_rather_than_showing_a_ghost(home: Home) -> None:
    entry = home.session(os.getpid(), "dddddddd-0000-4000-8000-000000000004", status="busy")
    (home.root / "sessions" / f"{entry['pid']}.json").write_text(
        json.dumps({**entry, "procStart": "1"})
    )
    assert "No live sessions" in routes.render_board()


@pytest.mark.unit
def test_a_format_that_moved_is_named_on_the_board(home: Home) -> None:
    """docs/adr/0004: a visible banner, not a None at a call site."""
    entry = home.session(os.getpid(), "eeeeeeee-0000-4000-8000-000000000005")
    del entry["status"]
    (home.root / "sessions" / f"{entry['pid']}.json").write_text(json.dumps(entry))

    html = routes.render_board()
    assert "notice" in html
    assert "status" in html


@pytest.mark.unit
def test_transcript_content_is_escaped_before_it_reaches_the_page(home: Home) -> None:
    """A transcript holds anything the human pasted, including markup (docs/07-security.md)."""
    home.session(os.getpid(), "ffffffff-0000-4000-8000-000000000006")
    home.transcript(
        "ffffffff-0000-4000-8000-000000000006",
        {"type": "ai-title", "aiTitle": "<script>alert(1)</script>"},
        _entry("assistant", "<img src=x onerror=alert(1)>"),
    )
    html = routes.render_board()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html


@pytest.mark.unit
def test_a_row_expands_to_the_tail_of_its_transcript(home: Home) -> None:
    home.session(os.getpid(), "aaaaaaaa-0000-4000-8000-000000000001")
    home.transcript(
        "aaaaaaaa-0000-4000-8000-000000000001",
        _entry("user", "the question"),
        _entry("assistant", "the answer"),
        {**_entry("assistant", "the subagent"), "isSidechain": True},
    )
    html = routes.render_tail("aaaaaaaa-0000-4000-8000-000000000001")
    assert "the question" in html
    assert "the answer" in html
    assert "the subagent" not in html


@pytest.mark.unit
def test_a_session_id_that_is_not_one_reaches_no_glob(home: Home) -> None:
    """The id arrives from a URL path and is interpolated into a glob; it is refused, not fixed."""
    assert "no transcript" in routes.render_tail("../../../etc/passwd")


@pytest.fixture
async def wired(
    home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Store]:
    """The board tests that go through a route need a store, because the page now has two halves."""
    store = Store(tmp_path / "blocks.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


@pytest.mark.unit
async def test_the_page_serves_the_board_and_opens_one_stream(home: Home, wired: Store) -> None:
    body = (await routes.page()).body.decode()
    assert "No live sessions" in body
    assert "new EventSource('/events')" in body


@pytest.mark.unit
async def test_the_stream_pushes_the_board_and_then_stays_quiet(home: Home, wired: Store) -> None:
    home.session(os.getpid(), "aaaaaaaa-0000-4000-8000-000000000001")
    events = sse.board_events()

    first = await anext(events)
    assert first.startswith("event: board")
    assert first.endswith("\n\n")
    # A multi-line fragment is one `data:` field per line; that is the protocol, not a preference.
    assert all(line.startswith("data: ") for line in first.strip().splitlines()[1:])
    assert "example" in first

    # The blocks channel is pushed once too, and then nothing changes — but the page is still told
    # that somebody looked, because "quiet" and "gone" must not look alike.
    assert (await anext(events)).startswith("event: blocks")
    second = await anext(events)
    assert second.startswith("event: heartbeat")
    assert "<article" not in second
    await events.aclose()


@pytest.mark.unit
async def test_the_page_says_when_it_last_heard_from_the_server(home: Home, wired: Store) -> None:
    """A board that has silently stopped updating looks exactly like a quiet one (CLAUDE.md).

    Both halves of docs/06-console.md are asserted: the stream dropping, and the stream staying
    open while nothing arrives. The second is pinned down to the rendered number, because the
    number is interpolated into JavaScript — an empty one is a syntax error that takes every
    script on the page with it, and a page frozen at first paint still renders a plausible board.
    """
    body = (await routes.page()).body.decode()
    assert 'id="asof"' in body
    assert "stream lost" in body
    assert "heartbeat" in body
    assert "stream stalled" in body
    assert "const silence = 0.0 * 3 * 1000;" in body


@pytest.mark.unit
async def test_a_template_asking_for_something_the_route_did_not_pass_fails_loudly(
    home: Home,
) -> None:
    """The failure above, made structural rather than remembered."""
    with pytest.raises(UndefinedError):
        routes.env.from_string("{{ never_passed }}").render()


async def _request(path: str, host: str) -> tuple[int, str]:
    """Drive the ASGI application directly: the middleware and the routing, with no test client.

    `httpx` is deliberately absent from this project's dependencies, and a dependency added to
    reach a route is a dependency in the lock file forever.
    """
    from agent_desk.web.app import app

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", host.encode())],
        "client": ("127.0.0.1", 54321),
        "server": ("127.0.0.1", 8787),
    }
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body.decode()


@pytest.mark.unit
async def test_the_console_answers_a_loopback_host(home: Home, wired: Store) -> None:
    home.session(os.getpid(), "aaaaaaaa-0000-4000-8000-000000000001")
    status, body = await _request("/", "127.0.0.1:8787")
    assert status == 200
    assert "agent-desk" in body


@pytest.mark.unit
async def test_a_page_on_the_web_cannot_read_this_console_through_the_browser(home: Home) -> None:
    """A hostname resolving to 127.0.0.1 is same-origin to a browser, and the reply is transcript
    text. Loopback keeps other users off the port; the Host check keeps other *pages* off it
    (docs/07-security.md)."""
    status, _ = await _request("/", "board.attacker.example")
    assert status == 400

    status, _ = await _request(
        "/sessions/aaaaaaaa-0000-4000-8000-000000000001/tail", "board.attacker.example"
    )
    assert status == 400

    # /events is the route that keeps sending, which makes it the one worth stealing.
    status, _ = await _request("/events", "board.attacker.example")
    assert status == 400


@pytest.mark.unit
def test_a_transcript_that_cannot_be_read_leaves_the_row_marked(home: Home) -> None:
    """Present but unreadable is not the same as quiet, and the row must not pretend otherwise."""
    home.session(os.getpid(), "aaaaaaaa-0000-4000-8000-000000000001")
    directory = home.root / "projects" / "-broken"
    directory.mkdir(parents=True)
    (directory / "aaaaaaaa-0000-4000-8000-000000000001.jsonl").write_text("torn\n")

    html = routes.render_board()
    assert "registry facts only" in html


# --- the console as a thing a person uses -------------------------------------------------------
@pytest.mark.unit
async def test_the_console_is_reachable_without_a_mouse(home: Home, wired: Store) -> None:
    """Three affordances that are easy to leave out and expensive to add back.

    A session row is a native `<details>`, so opening one works from the keyboard and is announced
    by a screen reader — it used to be a `div` with a click handler, which is neither. Every input
    has a label. And the field can be reached from anywhere with one key, because this window
    hovers over a terminal and reaching for the mouse is what it exists to save.
    """
    home.session(os.getpid(), "aaaaaaaa-0000-4000-8000-000000000001")
    body = (await routes.page()).body.decode()

    assert '<details class="row' in body
    assert "<summary>" in body
    assert 'for="ask-text"' in body and 'id="ask-text"' in body
    assert "event.key === '/'" in body
    # And the row still works with no JavaScript at all: the disclosure is native and the tail has
    # a plain link inside it until a script replaces it.
    assert 'href="/sessions/aaaaaaaa-0000-4000-8000-000000000001/tail"' in body


@pytest.mark.unit
async def test_the_styles_are_one_file_rather_than_four_copies(home: Home, wired: Store) -> None:
    """They were inline in four pages, which is how the four drifted apart."""
    from agent_desk.web.routes import TEMPLATES

    stylesheet = TEMPLATES.parent / "static" / "console.css"
    assert stylesheet.is_file()

    for page in ("board.html", "inbox.html", "viewers.html"):
        markup = (TEMPLATES / page).read_text()
        assert '<link rel="stylesheet" href="/static/console.css">' in markup, page
        assert "<style>" not in markup, f"{page} still carries its own copy"


@pytest.mark.unit
async def test_an_empty_console_says_what_to_do_next(home: Home, wired: Store) -> None:
    """An empty state that only says "empty" makes a first run feel broken."""
    body = (await routes.page()).body.decode()

    assert "No live sessions" in body
    assert "claude" in body
    assert "Nothing asked yet" in body
    assert "/idea" in body
