"""The one write path, and the four things that must stay true about it.

docs/adr/0002-read-first-never-interrupt.md: reading a session is invisible to it, and writing to
one costs its context. This module is the single exception, and every test here is about the
exception staying small.
"""

from __future__ import annotations

import ast
import json
import pathlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from agent_desk import peer
from agent_desk.config import Settings
from agent_desk.observe import registry, transcript
from agent_desk.observe.model import Session
from agent_desk.store.repo import Store
from agent_desk.web import routes

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
PKG = pathlib.Path(peer.__file__).parent


def _session(**overrides: Any) -> Session:
    entry: dict[str, Any] = json.loads((FIXTURES / "registry_entry.json").read_text())
    entry.update(overrides)
    return Session.model_validate(entry)


# --- the refusal ----------------------------------------------------------------------------
@pytest.mark.unit
def test_a_message_is_not_delivered_and_the_report_says_why() -> None:
    """`delivered` is a fact. A path that cannot deliver must never report that it did.

    The installed CLI publishes no client for its cross-session socket, and guessing the protocol
    would put a malformed prompt into a running session's queue — the one thing docs/adr/0002
    refuses to risk.
    """
    delivery = peer.send(_session(), "have you pushed duck-129?")

    assert delivery.delivered is False
    assert "needs_toolchain" in delivery.detail
    # The reason names the missing capability rather than reading like a bug in this console.
    assert "claude CLI" in delivery.detail


@pytest.mark.unit
def test_the_refusal_names_the_path_that_does_work() -> None:
    """docs/08-non-goals.md §2 and §3: no queue that delivers later, no typing into a terminal.

    What is left is a human carrying the text, which is the same answer the ideas module gives.
    """
    assert "paste it yourself" in peer.send(_session(), "anything").detail


# --- the exception staying small -------------------------------------------------------------
@pytest.mark.unit
def test_the_write_path_opens_nothing() -> None:
    """It reads no credential, no socket and no file at all.

    Authentication on that socket is by kernel peer credentials rather than by a secret this
    program would hold, which is why the rule against opening `sessions/*.key` costs this module
    nothing — it would not have used one.
    """
    tree = ast.parse((PKG / "peer.py").read_text())
    imported = {
        name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
        )
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    # Prose may name a socket in order to explain why this module does not open one; code may not.
    assert imported == {"__future__", "dataclasses", "agent_desk"}
    assert "open" not in called


@pytest.mark.unit
def test_no_background_path_can_reach_it() -> None:
    """The import-graph rule of design/01-module-layout.md, which until now guarded an empty file.

    A module that can import `peer` is a module that can message a session without a human, and
    the property the whole tool rests on stops being structural.
    """
    offenders = []
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG)
        if rel.parts[0] == "web" or rel.name == "peer.py":
            continue
        if "peer" in path.read_text().replace("peer-messaging", "").replace("peerProtocol", ""):
            source = path.read_text()
            if "import peer" in source or "from agent_desk import peer" in source:
                offenders.append(str(rel))
    assert not offenders, f"only web/ may import the write path: {offenders}"


# --- the surface a human uses -----------------------------------------------------------------
@pytest.fixture
async def console(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    """A board with one live session on it, and a store, wired as the application wires them."""
    from tests.unit.test_board import Home, _starttime

    fake = Settings(claude_home=tmp_path / "claude", data_dir=tmp_path / "data")
    for module in (registry, transcript, routes):
        monkeypatch.setattr(module, "settings", fake)
    home = Home(tmp_path / "claude")

    import os

    session_id = "aaaaaaaa-0000-4000-8000-000000000001"
    home.session(os.getpid(), session_id, cwd="/home/dev/projects/alpha")
    assert _starttime(os.getpid())

    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield session_id
    await store.close()


@pytest.mark.unit
def test_opening_the_panel_sends_nothing(console: str) -> None:
    """The button opens a panel. Nothing about opening it reaches a session."""
    panel = routes.render_message("compose", console)

    assert "message to" in panel
    assert "alpha" in panel
    assert "Review it" in panel
    assert "Send it" not in panel


@pytest.mark.unit
def test_the_message_is_shown_in_full_beside_the_session_it_would_reach(console: str) -> None:
    """docs/06-console.md: shown in full before it goes, against the name of the session.

    Not summarised and not truncated — what is on the screen is what would arrive.
    """
    text = "have you pushed duck-129?\n\nsecond paragraph that a summary would have eaten"
    panel = routes.render_message("confirm", console, text)

    assert "second paragraph that a summary would have eaten" in panel
    assert "alpha" in panel
    assert "Send it" in panel


@pytest.mark.unit
def test_a_session_that_left_the_board_cannot_be_messaged(console: str) -> None:
    """The target is resolved from the registry at the moment of the click, not from the form."""
    panel = routes.render_message("compose", "bbbbbbbb-0000-4000-8000-000000000002")

    assert "no longer on the board" in panel
    assert "Send it" not in panel


@pytest.mark.unit
def test_the_refusal_offers_the_text_back(console: str) -> None:
    panel = routes.render_message("refused", console, "the message", peer.NEEDS_CLIENT)

    assert "not delivered" in panel
    assert "the message" in panel
    assert "Copy it" in panel


@pytest.mark.unit
async def test_the_route_reaches_the_write_path_and_reports_the_refusal(console: str) -> None:
    """End to end through the real ASGI stack: the click, and what came back from it."""
    from tests.unit.test_input import _post

    status, html, _ = await _post(
        f"/sessions/{console}/message/send", {"text": "have you pushed duck-129?"}
    )

    assert status == 200
    assert "not delivered" in html
    assert "needs_toolchain" in html
    assert "have you pushed duck-129?" in html


@pytest.mark.unit
async def test_an_empty_message_never_reaches_the_write_path(console: str) -> None:
    """A blank submit is not a message, and the confirm step is not skippable by sending one."""
    from tests.unit.test_input import _post

    status, html, _ = await _post(f"/sessions/{console}/message/review", {"text": "   "})

    assert status == 200
    assert "Send it" not in html
