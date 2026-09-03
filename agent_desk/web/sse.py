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
from agent_desk.web.routes import render_blocks, render_board

router = APIRouter()


def _event(name: str, html: str) -> str:
    """One named event. Each line of the fragment is its own `data:` field, which is how the
    protocol carries a multi-line payload; EventSource rejoins them with newlines.

    The board and the blocks are two channels on one connection rather than two connections: a
    second EventSource would be a second polling loop over the same filesystem, and the page needs
    to tell "the board moved" from "an answer arrived" anyway.
    """
    body = "\n".join(f"data: {line}" for line in html.splitlines())
    return f"event: {name}\n{body}\n\n"


# A named event rather than a comment, because the page has to be able to tell "nothing changed"
# from "nobody is reading the registry any more". A comment reaches the browser but not the
# script, which would leave a board that had silently stopped updating looking exactly like a
# board on which nothing is happening — the fifth rule of CLAUDE.md, in the shape a console takes
# it.
_HEARTBEAT = "event: heartbeat\ndata: checked\n\n"


async def board_events() -> AsyncIterator[str]:
    """The rendered board whenever it changes, and a comment when it does not.

    The heartbeat is not decoration. Without a write, a server never learns that the browser went
    away, and this generator would poll the filesystem for a window that closed an hour ago; and
    without a *named* event, the page could not put a time on what it is showing.
    """
    previous: dict[str, str] = {}
    while True:
        pushed = False
        for name, html in (
            ("board", await asyncio.to_thread(render_board)),
            ("blocks", await render_blocks()),
        ):
            if previous.get(name) != html:
                previous[name] = html
                pushed = True
                yield _event(name, html)
        if not pushed:
            yield _HEARTBEAT
        await asyncio.sleep(settings.registry_poll_seconds)


@router.get("/events")
async def events() -> StreamingResponse:
    return StreamingResponse(
        board_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
