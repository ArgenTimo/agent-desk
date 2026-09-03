"""The console: one process, one page, bound to loopback.

`127.0.0.1` is load-bearing rather than a default. Anything that can reach this port can already
read `~/.claude/` as the same operating-system user, which is the entire v1 security model; the day
it becomes `0.0.0.0` the tool needs a real one (docs/07-security.md).
"""

from __future__ import annotations

from fastapi import FastAPI

from agent_desk.web import routes, sse

# No OpenAPI surface: this application has three read-only routes and no client but the page it
# serves.
app = FastAPI(title="agent-desk", openapi_url=None)
app.include_router(routes.router)
app.include_router(sse.router)
