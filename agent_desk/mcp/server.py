"""The MCP server: JSON-RPC over stdin and stdout, and nothing else.

*«Возможность подключаться к этому проекту по MCP.»*

## Written out rather than pulled in

There is no MCP library in this environment and no network to fetch one. The stdio transport is
newline-delimited JSON-RPC 2.0 and the part of it this needs is four methods, so it is written here
— which is also the answer to "what did adding this cost": one file, no dependency, and a shape
this repository can read.

## It is a reader that may add a row

The console owns the loop, the runs and the agents; this owns nothing. It opens the same store, and
what it can do is bounded by `tools.py`, where every call says whether it writes. Nothing here
starts an agent, cancels a run, or deletes anything — the expensive and irreversible acts stay on
the page, behind a person's click (docs/adr/0002, docs/adr/0007).

## One line in, one line out

A framing bug in a server nobody can attach a debugger to is a server that hangs. So: read a line,
parse it, answer it, flush. A notification — a message with no `id` — is answered with nothing at
all, which is what JSON-RPC says and what a client waiting for a reply to `initialized` would hang
on.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from agent_desk.config import settings
from agent_desk.mcp import tools
from agent_desk.store.repo import Store

# What this server claims to speak. Named rather than echoed back from the client: a server that
# agrees to whatever it is told is one that will one day agree to something it cannot do.
PROTOCOL = "2024-11-05"

NAME = "agent-desk"


def _reply(at: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": at, "result": result}


def _refuse(at: Any, code: int, why: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": at, "error": {"code": code, "message": why}}


def _tools_said() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": one.name,
                "description": one.says,
                "inputSchema": one.takes,
                # MCP's own word for "this changes something". Said per tool rather than once for
                # the server, so a client can tell the two kinds apart without reading prose.
                "annotations": {"readOnlyHint": not one.writes, "destructiveHint": False},
            }
            for one in tools.TOOLS
        ]
    }


async def answer(store: Store, said: dict[str, Any]) -> dict[str, Any] | None:
    """One request in, one reply out — or `None` for a notification.

    Unknown methods are refused by code rather than ignored: a client that asked for something this
    does not have should find out now, not by waiting.
    """
    method = said.get("method", "")
    at = said.get("id")
    if at is None:
        # A notification. `initialized` is the one that matters and it wants no answer at all.
        return None
    if method == "initialize":
        return _reply(
            at,
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": NAME, "version": "1"},
            },
        )
    if method == "tools/list":
        return _reply(at, _tools_said())
    if method == "tools/call":
        given = said.get("params") or {}
        return _reply(
            at,
            await tools.call(store, str(given.get("name", "")), given.get("arguments") or {}),
        )
    if method == "ping":
        return _reply(at, {})
    return _refuse(at, -32601, f"this server does not have {method}")


async def serve(reader: asyncio.StreamReader, write: Any, store: Store) -> None:
    """Read a line, answer it, flush. Until stdin closes.

    A line that is not JSON is refused and the loop carries on: one malformed message is not a
    reason to take down a server that another tool call is about to use.
    """
    while True:
        line = await reader.readline()
        if not line:
            return
        try:
            said = json.loads(line)
        except ValueError:
            write(json.dumps(_refuse(None, -32700, "that was not JSON")))
            continue
        if not isinstance(said, dict):
            write(json.dumps(_refuse(None, -32600, "a request is an object")))
            continue
        back = await answer(store, said)
        if back is not None:
            write(json.dumps(back))


async def run() -> None:  # pragma: no cover - the process entry point
    """Open the store beside the console's and talk on stdin.

    The same file the console has open. That is what WAL is for, and it is why this can be a second
    process rather than a route: an agent's tool call does not wait on a browser being open.
    """
    store = Store(settings.db_path)
    await store.open()
    reader = asyncio.StreamReader()
    await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
    )

    def write(said: str) -> None:
        sys.stdout.write(said + "\n")
        sys.stdout.flush()

    try:
        await serve(reader, write, store)
    finally:
        await store.close()


def main() -> None:  # pragma: no cover - the process entry point
    asyncio.run(run())
