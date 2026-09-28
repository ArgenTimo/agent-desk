"""The MCP server offers what its client asked for, and a session gets the inbox (B5).

`.mcp.json` in this repository starts the installed copy (A2) with four tools: write an idea, read
the open ones, leave a question for a person, read its answer. The workbench, the runs and the
scripts are the server's too, and a session is not handed them.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from agent_desk.config import Settings
from agent_desk.mcp import server, tools
from agent_desk.store.repo import Store

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[2]
FOUR = ["keep_idea", "open_ideas", "ask", "answer"]


def test_an_empty_setting_offers_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "settings", Settings(mcp_tools=""))

    assert server.offered() == tools.TOOLS


async def test_a_named_set_is_what_is_listed_and_the_rest_is_refused(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "settings", Settings(mcp_tools=",".join(FOUR)))
    store = Store(tmp_path / "agent-desk.db")
    await store.open(recover=False)
    try:
        listed = await server.answer(store, {"id": 1, "method": "tools/list"})
        refused = await server.answer(
            store, {"id": 2, "method": "tools/call", "params": {"name": "run", "arguments": {}}}
        )
        kept = await server.answer(
            store,
            {
                "id": 3,
                "method": "tools/call",
                "params": {"name": "keep_idea", "arguments": {"text": "a thought from a session"}},
            },
        )
        ideas = await store.ideas()
    finally:
        await store.close()

    assert listed is not None and [one["name"] for one in listed["result"]["tools"]] == FOUR
    assert refused is not None and "There is no tool called run" in json.dumps(refused)
    assert kept is not None and [one.text for one in ideas] == ["a thought from a session"]


def test_this_repository_starts_the_installed_copy_with_the_four() -> None:
    """The working console's copy, not this checkout: a session's idea goes to the inbox a person
    reads, and a branch being edited here is not what answers it (A2, A5)."""
    config = json.loads((ROOT / ".mcp.json").read_text())
    desk = config["mcpServers"]["agent-desk"]

    assert desk["command"] == "${HOME}/opt/agent-desk-prod/.venv/bin/python"
    assert desk["args"] == ["-m", "agent_desk.mcp"]
    assert desk["env"]["AGENT_DESK_MCP_TOOLS"].split(",") == FOUR
