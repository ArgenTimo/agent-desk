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

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agent_desk.web import routes, sse

# No OpenAPI surface: this application has three read-only routes and no client but the page it
# serves.
app = FastAPI(title="agent-desk", openapi_url=None)
# Loopback names only, and deliberately not `settings.host`: that is a bind address, and reading
# it here would let a changed bind silently widen the one check docs/07-security.md says never to
# widen. A non-loopback bind is outside the v1 security model altogether.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.include_router(routes.router)
app.include_router(sse.router)
