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

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# `same-origin` is this page; `none` is a typed URL or a bookmark. `cross-site` and `same-site`
# are somebody else's page, and neither has business changing anything here.
ALLOWED_SITES = frozenset({"same-origin", "none"})


def _header(scope: Scope, wanted: bytes) -> str | None:
    """One header, read without assuming anything about the others.

    Decoding every header as UTF-8 to find one of them made a single stray byte an unauthenticated
    remote 500 — on the network bind, in the layer that runs *before* a token is checked, with a
    traceback per hit. Header values are bytes on the wire; `latin-1` is the mapping that cannot
    fail, and this only ever compares the result to a known word.
    """
    for key, value in scope["headers"]:
        if bytes(key).lower() == wanted:
            return str(bytes(value).decode("latin-1")).lower()
    return None


class SameOriginOnly:
    """Refuse a state-changing request that a foreign page caused, and refuse to be framed.

    The second half is not a separate concern. A form submitted from inside an `iframe` of this
    page carries `Sec-Fetch-Site: same-origin`, because it is: the fix for a foreign *page* does
    nothing about a foreign page wearing this one as a frame, so a click landing where the
    attacker chose would pass every check above it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope["method"] not in SAFE_METHODS:
            await self._guard(scope, receive, send)
            return
        await self.app(scope, receive, self._unframed(send))

    @staticmethod
    def _unframed(send: Send) -> Send:
        async def sending(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [
                    *message["headers"],
                    (b"x-frame-options", b"DENY"),
                    (b"content-security-policy", b"frame-ancestors 'none'"),
                    # The shared view's token is in the URL, so a link out of that page would
                    # hand it to whoever the link points at. There are no links today; this is
                    # the cheap insurance against the first one.
                    (b"referrer-policy", b"no-referrer"),
                ]
            await send(message)

        return sending

    async def _guard(self, scope: Scope, receive: Receive, send: Send) -> None:
        site = _header(scope, b"sec-fetch-site")
        if site is not None and site not in ALLOWED_SITES:
            response = PlainTextResponse(
                "This page only accepts actions from its own forms.", status_code=403
            )
            await response(scope, receive, self._unframed(send))
            return

        await self.app(scope, receive, self._unframed(send))


def guard(app: ASGIApp) -> SameOriginOnly:
    """Wrap an application so the guard is the *outermost* layer.

    Added as middleware it sat inside Starlette's error handler, so a 500 answered with neither
    frame header — the one response an attacker can most easily provoke. Outside it, every byte
    this process sends passes through here.
    """
    return SameOriginOnly(app)
