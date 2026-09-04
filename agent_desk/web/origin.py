"""A state-changing request must come from this console, not from a page that links to it.

The console binds to loopback and checks the `Host` header, and neither of those stops this: a
form on any website can post to `http://127.0.0.1:8787/blocks` without asking CORS for permission,
and the request carries the right `Host` because it really is going there. The victim is whoever
has the console open — the browser attaches nothing secret, but nothing secret is needed to submit
a question, discard an idea, or press send on the one path that writes to a session.

The defence is the fetch metadata every current browser attaches and no page can forge:
`Sec-Fetch-Site` says whether the request came from this origin, and a cross-site form post says
so about itself. A request without that header is not a browser — it is `curl`, a test, or a
script run by the same operating-system user, who can already read `~/.claude/` and does not need
a form to do harm (docs/07-security.md).

Reads are left alone. Nothing here changes state on a GET, which is a rule worth keeping for its
own sake.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# `same-origin` is this page; `none` is a typed URL or a bookmark. `cross-site` and `same-site`
# are somebody else's page, and neither has business changing anything here.
ALLOWED_SITES = frozenset({"same-origin", "none"})


class SameOriginOnly:
    """Refuse a state-changing request that a foreign page caused."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        site = headers.get("sec-fetch-site")
        if site is not None and site not in ALLOWED_SITES:
            response = PlainTextResponse(
                "This console only accepts actions from its own pages.", status_code=403
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def guard(app: ASGIApp) -> Callable[[Scope, Receive, Send], Awaitable[None]]:
    return SameOriginOnly(app)
