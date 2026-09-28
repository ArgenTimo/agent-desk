"""One console per data directory, and a guest that opens the store leaves the console's blocks alone.

R1 in _research/04_dogfooding_gaps.md: every `Store.open()` assumed it was the only process on the
file, so the MCP server, a second console, or a restart under `--reload` marked the running
console's blocks failed. A3 in _research/06_backlog.md.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import lock
from agent_desk.mcp import server
from agent_desk.store.repo import Store
from agent_desk.web import routes
from agent_desk.web.app import app

pytestmark = pytest.mark.unit


async def _a_running_block(path: pathlib.Path) -> str:
    store = Store(path)
    await store.open()
    try:
        thread = await store.create_thread("s")
        block = await store.create_block(
            thread_id=thread.id, kind="question", input="?", thread_set_by="human"
        )
        await store.set_block_running(block.id)
        return block.id
    finally:
        await store.close()


async def _state(path: pathlib.Path, block_id: str) -> str:
    store = Store(path)
    await store.open(recover=False)
    try:
        block = await store.block(block_id)
        assert block is not None
        return block.state
    finally:
        await store.close()


async def test_the_mcp_server_opens_the_store_without_failing_the_consoles_blocks(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "agent-desk.db"
    block_id = await _a_running_block(path)
    monkeypatch.setattr(server, "settings", type("S", (), {"db_path": path})())

    store = await server.open_store()
    await store.close()

    assert await _state(path, block_id) == "running"


async def test_the_console_itself_still_recovers_what_it_was_running(
    tmp_path: pathlib.Path,
) -> None:
    """The other half: the crash rule is the console's, and it still applies there."""
    path = tmp_path / "agent-desk.db"
    block_id = await _a_running_block(path)

    store = Store(path)
    await store.open()
    await store.close()

    assert await _state(path, block_id) == "failed"


def test_a_second_hold_on_one_data_directory_is_refused_and_says_by_whom(
    tmp_path: pathlib.Path,
) -> None:
    with lock.hold(tmp_path), pytest.raises(lock.AlreadyRunning, match=r"pid \d+.*already running"):
        with lock.hold(tmp_path):
            pass


def test_the_lock_is_free_again_once_the_holder_lets_go(tmp_path: pathlib.Path) -> None:
    with lock.hold(tmp_path):
        pass
    with lock.hold(tmp_path):
        pass


async def test_a_second_console_on_the_same_data_directory_does_not_start(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And it refuses before it opens the store, so the first console's blocks are untouched."""
    from agent_desk.config import settings

    path = tmp_path / "console.db"
    block_id = await _a_running_block(path)
    monkeypatch.setattr(routes, "store", Store(path))

    with lock.hold(settings.data_dir), pytest.raises(lock.AlreadyRunning):
        async with app.router.lifespan_context(app):
            pass

    assert await _state(path, block_id) == "running"
