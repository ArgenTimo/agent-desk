"""The console: one process, one page, bound to loopback.

`127.0.0.1` is load-bearing rather than a default. Anything that can reach this port can already
read `~/.claude/` as the same operating-system user, which is the entire v1 security model; the day
it becomes `0.0.0.0` the tool needs a real one (docs/07-security.md).

That argument covers every client except the one that matters most here: a browser. A page on the
open web can resolve its own hostname to `127.0.0.1` and have the user's browser read this console
for it — same origin as far as the browser is concerned, and the response is transcript text. So
the application answers only to a `Host` naming loopback, and refuses anything else before a route
sees it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agent_desk.web import blocks, routes, sse
from agent_desk.web.origin import guard

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the store, hold one task group for every run, and end them on the way out.

    The group is the mechanism behind "no fire-and-forget task": a run that raises is observed
    here rather than swallowed by the event loop. Shutdown cancels what is in flight instead of
    waiting for it — a console that will not close while three questions are in the air is the
    same failure as one that will not close while a browser is watching the board.
    """
    await routes.store.open()
    try:
        async with asyncio.TaskGroup() as group:
            blocks.runs.attach(group)
            try:
                yield
            finally:
                # Every block still in flight is stopped and says so. Without the second half a
                # run cancelled before its first step leaves a block `queued` with nothing behind
                # it, which the crash rule deliberately does not clean up on the next start.
                for block_id in blocks.runs.cancel_all():
                    with suppress(Exception):
                        await blocks.cancel(routes.store, block_id)
                blocks.runs.attach(None)
    finally:
        await routes.store.close()


# No OpenAPI surface: this application has a handful of read-mostly routes and no client but the
# page it serves.
app = FastAPI(title="agent-desk", openapi_url=None, lifespan=lifespan)
# Loopback names only, and deliberately not `settings.host`: that is a bind address, and reading
# it here would let a changed bind silently widen the one check docs/07-security.md says never to
# widen. A non-loopback bind is outside the v1 security model altogether.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
if STATIC.is_dir():
    # HTMX, vendored rather than fetched: a local tool that needs the network to render a list of
    # five sessions has lost the argument (docs/adr/0003).
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(routes.router)
app.include_router(sse.router)

# A form on any website can post here without asking CORS, and the Host check passes because the
# request really is going to loopback. Fetch metadata is what separates this console's own pages
# from somebody else's — and the guard wraps the application from *outside*, so that a 500 raised
# anywhere within it still carries the frame headers (agent_desk/web/origin.py).
asgi = guard(app)
