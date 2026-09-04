"""Serve the console, and — only when asked — the shared view beside it.

One process, two binds (docs/adr/0003 keeps the first half; docs/07-security.md requires the
second). The console stays on loopback and holds everything: the board, the input field, the
blocks, the ideas inbox and the one write path. The shared view is a different application on a
different port with two routes and no way to reach any of that.

The separation is the point. A single application that decided per request whether a viewer may
see the board would work, and it would be one bad conditional away from not working; two
applications cannot be got wrong that way.
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn
from starlette.types import ASGIApp

from agent_desk.config import settings
from agent_desk.web import routes, shared
from agent_desk.web.app import asgi as console


def silence_access_logging() -> None:
    """Turn the request log off for this process, and mean it.

    `access_log=False` on one server is not a property of that server: uvicorn implements it by
    stripping the handlers off the process-wide `uvicorn.access` logger when a config loads, and
    every connection then asks that one logger whether it has any. Two servers therefore fight,
    and the winner is whichever loaded last — so the token stayed out of the log because of the
    order two list entries happened to be in, with nothing saying so.

    A viewer's token is a path segment and the access log writes paths. That is reason enough to
    have no request log at all: what this program wants recorded, it records itself, by name and
    by count (docs/07-security.md).
    """
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True


def _config(target: ASGIApp, host: str, port: int) -> uvicorn.Config:
    return uvicorn.Config(
        target,
        host=host,
        port=port,
        access_log=False,
        # The console's event stream never ends by design, so a graceful stop that waits for open
        # responses waits forever. Measured once, in Phase 1, with a browser attached.
        timeout_graceful_shutdown=2,
    )


async def serve() -> None:
    silence_access_logging()
    servers = [uvicorn.Server(_config(console, settings.host, settings.port))]

    if settings.share_host:
        # The shared application never opens or closes the store; the console's lifespan owns it.
        shared.app.state.store = routes.store
        servers.append(
            uvicorn.Server(_config(shared.asgi, settings.share_host, settings.share_port))
        )

    async with asyncio.TaskGroup() as group:
        for server in servers:
            group.create_task(server.serve())


def main() -> None:
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:  # pragma: no cover - Ctrl-C is not a failure
        pass


if __name__ == "__main__":
    main()
