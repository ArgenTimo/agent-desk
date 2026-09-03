"""The live board, as server-sent events.

The stream is one direction: the server re-reads the registry on a timer and pushes the rendered
board when it differs from what it pushed last. Nothing arrives on this connection, and nothing on
it can reach a session — polling files is invisible to the agents being polled, which is the
property the whole tool rests on (docs/adr/0002).

Reading is done in a thread: a blocking `open()` on an async path stalls the console for every
viewer of it, and there is only one process (docs/adr/0003).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from agent_desk.config import settings
from agent_desk.web.routes import render_board

router = APIRouter()


def _event(html: str) -> str:
    """One `message` event. Each line of the fragment is its own `data:` field, which is how the
    protocol carries a multi-line payload; EventSource rejoins them with newlines."""
    body = "\n".join(f"data: {line}" for line in html.splitlines())
    return f"{body}\n\n"


async def board_events() -> AsyncIterator[str]:
    """The rendered board whenever it changes, and a comment when it does not.

    The comment is not decoration: without a write, a server never learns that the browser went
    away, and this generator would poll the filesystem for a window that closed an hour ago.
    """
    previous: str | None = None
    while True:
        html = await asyncio.to_thread(render_board)
        if html != previous:
            previous = html
            yield _event(html)
        else:
            yield ": no change\n\n"
        await asyncio.sleep(settings.registry_poll_seconds)


@router.get("/events")
async def events() -> StreamingResponse:
    return StreamingResponse(
        board_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
