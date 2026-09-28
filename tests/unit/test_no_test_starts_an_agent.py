"""A test run starts no agent, asks no model and opens nothing of this machine's (tests/conftest.py).

Two doors, and the first guard here only closed one. It patched `dispatch.settings`, so
`claude --bg` stopped; `agent_desk.answer.session` reads the same settings object under its own
name and went on spending real `claude -p` calls — seventeen of them in one `make gate`, which the
Stop hook runs at every turn end. Both are asserted below, because a guard that covers one door
reads exactly like a guard that covers both.
"""

from __future__ import annotations

import pathlib
import shutil

import pytest
from agent_desk.answer import session
from agent_desk.config import settings
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes

pytestmark = pytest.mark.unit


def test_the_store_the_suite_opens_is_not_the_consoles() -> None:
    """`web/routes.py` opens `settings.db_path` at import; without the redirect that is the live
    database, migrated by whatever branch ran the gate."""
    home = pathlib.Path.home()

    assert not settings.data_dir.is_relative_to(home / ".local" / "share" / "agent-desk")
    assert routes.store.path.parent == settings.data_dir
    assert not settings.claude_home.is_relative_to(home / ".claude")


def test_the_engine_a_test_asks_is_not_installed() -> None:
    """The door the first guard left open: the answer engine's own view of the binary."""
    named = session.argv()[0]

    assert shutil.which(named) is None
    assert not pathlib.Path(named).exists()


async def test_a_request_about_the_console_with_no_stub_starts_nothing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact path that did it: a line taken as `master`, dispatched into this checkout."""
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    try:
        thread = await store.create_thread("a chat")
        block = await store.create_block(
            thread_id=thread.id, kind="question", input="бери в работу", thread_set_by="human"
        )

        await blocks.take_it_as(store, block, [], "master")

        assert all(task.agent_id in (None, "") for task in await store.tasks())
    finally:
        await store.close()
