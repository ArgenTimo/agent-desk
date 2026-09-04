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

import uvicorn
from fastapi import FastAPI

from agent_desk.config import settings
from agent_desk.web import routes, shared
from agent_desk.web.app import app as console


def _config(target: FastAPI, host: str, port: int, *, access_log: bool = True) -> uvicorn.Config:
    return uvicorn.Config(
        target,
        host=host,
        port=port,
        access_log=access_log,
        # The console's event stream never ends by design, so a graceful stop that waits for open
        # responses waits forever. Measured once, in Phase 1, with a browser attached.
        timeout_graceful_shutdown=2,
    )


async def serve() -> None:
    servers = [uvicorn.Server(_config(console, settings.host, settings.port))]

    if settings.share_host:
        # The shared application never opens or closes the store; the console's lifespan owns it.
        shared.app.state.store = routes.store
        # No access log on this bind, and the reason is the whole design of Phase 4. A viewer's
        # token is a path segment, so every default access line writes it in clear — beside the
        # structlog line naming the viewer, in the artefact most likely to be tailed, piped or
        # pasted into a bug report. The store deliberately keeps only a hash of that token; a log
        # that keeps the token itself undoes the care in one line (docs/07-security.md).
        servers.append(
            uvicorn.Server(
                _config(shared.app, settings.share_host, settings.share_port, access_log=False)
            )
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
