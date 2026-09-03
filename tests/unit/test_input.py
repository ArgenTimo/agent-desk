"""The input field: what it produces, and what it refuses to make you wait for.

docs/04-threads-and-blocks.md is the whole specification of this file. Its first claim is the one
worth testing hardest — submitting frees the field — because every other property here follows
from questions being independent errands rather than a queue.
"""

from __future__ import annotations

import asyncio
import pathlib
import time
from collections.abc import AsyncIterator

import pytest
from agent_desk.answer import session
from agent_desk.config import Settings
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes
from agent_desk.web.app import app

FAKE = """#!/bin/sh
here=$(dirname "$0")
prompt=$(cat)
case "$prompt" in
  *PLEASE_HANG*)
    printf '{"type":"assistant","message":{"content":[{"type":"text","text":"thinking"}]}}\\n'
    sleep 30 ;;
  *PLEASE_FAIL_ONCE*)
    if [ -f "$here/failed-once" ]; then
      printf '{"type":"assistant","message":{"content":[{"type":"text","text":"an answer"}]}}\n'
    else
      touch "$here/failed-once"
      exit 4
    fi ;;
  *) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"an answer"}]}}\\n' ;;
esac
"""


@pytest.fixture
def fake_claude(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    binary = tmp_path / "cli" / "claude"
    binary.parent.mkdir()
    binary.write_text(FAKE)
    binary.chmod(0o755)
    monkeypatch.setattr(
        session, "settings", Settings(claude_bin=str(binary), answer_timeout_seconds=5.0)
    )
    return binary


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    """A store and a task group, wired the way the application wires them."""
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    async with asyncio.TaskGroup() as group:
        blocks.runs.attach(group)
        try:
            yield store
        finally:
            blocks.runs.cancel_all()
            blocks.runs.attach(None)
    await store.close()


async def _state(store: Store, block_id: str) -> str:
    block = await store.block(block_id)
    assert block is not None
    return block.state


@pytest.mark.unit
async def test_submitting_frees_the_field(desk: Store, fake_claude: pathlib.Path) -> None:
    """The field is free before the answer exists, which is the point of a block."""
    started = time.monotonic()
    block = await blocks.submit(desk, "PLEASE_HANG — what about timeouts", [])
    elapsed = time.monotonic() - started

    # The fake sleeps for thirty seconds. Accepting the input took none of them.
    assert elapsed < 2
    assert await _state(desk, block.id) in ("queued", "running")


@pytest.mark.unit
async def test_several_questions_run_at_once_and_nothing_waits(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    first = await blocks.submit(desk, "PLEASE_HANG one", [])
    second = await blocks.submit(desk, "PLEASE_HANG two", [])
    await asyncio.sleep(0.4)

    assert await _state(desk, first.id) == "running"
    assert await _state(desk, second.id) == "running"
    assert len(blocks.runs) == 2


@pytest.mark.unit
async def test_an_answer_reaches_the_column(desk: Store, fake_claude: pathlib.Path) -> None:
    block = await blocks.submit(desk, "what about timeouts", [])
    for _ in range(50):
        if await _state(desk, block.id) == "answered":
            break
        await asyncio.sleep(0.1)

    assert await _state(desk, block.id) == "answered"
    column = await routes.render_blocks()
    assert "what about timeouts" in column
    assert "an answer" in column


@pytest.mark.unit
async def test_a_running_block_shows_what_it_has_said_so_far(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """docs/04: the question, then the answer as it streams.

    The partial lives in memory and nowhere else — an answer copied into a second place is a
    second thing to redact (design/02-data-model.md).
    """
    block = await blocks.submit(desk, "PLEASE_HANG and stream", [])
    for _ in range(50):
        if blocks.PARTIAL.get(block.id):
            break
        await asyncio.sleep(0.1)

    assert blocks.PARTIAL[block.id] == "thinking"
    assert "thinking" in await routes.render_blocks()


@pytest.mark.unit
async def test_cancelling_a_run_leaves_a_block_that_says_it_was_cancelled(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    block = await blocks.submit(desk, "PLEASE_HANG forever", [])
    await asyncio.sleep(0.3)
    assert blocks.cancel(block.id)

    for _ in range(50):
        if await _state(desk, block.id) == "cancelled":
            break
        await asyncio.sleep(0.1)
    assert await _state(desk, block.id) == "cancelled"
    assert block.id not in blocks.PARTIAL


@pytest.mark.unit
async def test_a_failed_block_can_be_retried_and_then_answers(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """It does not disappear, because a question that vanished is one you ask again.

    The fake fails the first time and answers the second, so this asserts that retry actually ran
    the question again rather than that the same input happens to succeed.
    """
    block = await blocks.submit(desk, "PLEASE_FAIL_ONCE", [])
    for _ in range(50):
        if await _state(desk, block.id) == "failed":
            break
        await asyncio.sleep(0.1)
    assert await _state(desk, block.id) == "failed"
    assert "retry" in await routes.render_blocks()

    stored = await desk.block(block.id)
    assert stored is not None
    await blocks.retry(desk, stored, [])
    for _ in range(50):
        if await _state(desk, block.id) == "answered":
            break
        await asyncio.sleep(0.1)
    assert await _state(desk, block.id) == "answered"


@pytest.mark.unit
async def test_the_console_stops_even_with_questions_in_the_air(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, fake_claude: pathlib.Path
) -> None:
    """Shutdown ends runs rather than waiting for them.

    A console that will not close while three questions are in flight is the shutdown hang this
    project already fixed once, wearing a different coat.
    """
    monkeypatch.setattr(routes, "store", Store(tmp_path / "lifespan.db"))
    started = time.monotonic()
    async with app.router.lifespan_context(app):
        await blocks.submit(routes.store, "PLEASE_HANG during shutdown", [])
        await asyncio.sleep(0.3)
    elapsed = time.monotonic() - started

    assert elapsed < 5
    assert len(blocks.runs) == 0


@pytest.mark.unit
def test_the_board_reaches_the_run_as_facts_and_not_as_a_guess() -> None:
    """docs/03-session-observation.md: the inference is this program's guess.

    Feeding a guess to a model that will then reason from it is how a guess becomes a fact, so the
    flag does not travel into the prompt — the status, the branch and the last entry do.
    """
    from agent_desk.observe.model import AttentionHint, Session, TailEntry, TranscriptTail
    from agent_desk.web.routes import BoardRow

    row = BoardRow(
        session=Session.model_validate(
            {
                "pid": 1,
                "procStart": "1",
                "sessionId": "s",
                "cwd": "/home/dev/projects/alpha",
                "name": "alpha-d0",
                "kind": "interactive",
                "version": "2.1.259",
                "status": "idle",
                "updatedAt": 0,
                "statusUpdatedAt": 0,
            }
        ),
        tail=TranscriptTail(
            session_id="s",
            title="Docker client",
            git_branch="boba/duck-129",
            entries=[TailEntry(role="assistant", text="reading the client")],
        ),
        hint=AttentionHint(waiting=True, observation="idle 14m · last entry: assistant"),
    )

    (line,) = blocks.board_lines([row])
    assert "alpha" in line
    assert "boba/duck-129" in line
    assert "reading the client" in line
    assert "waiting" not in line
    assert "may be waiting" not in line
