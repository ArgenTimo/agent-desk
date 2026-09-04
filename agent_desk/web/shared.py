"""The shared view: an ideas list, for someone who is not the owner of this machine.

Problem 5 of docs/01-vision.md — a teammate who does not write code wants to contribute an idea
and see what happened to the ones already there. docs/07-security.md is the page that governs it,
and it is emphatic about one thing: this is the point at which every other sentence in it stops
being sufficient.

Four decisions hold this surface down, and each is structural rather than a habit.

**It is a different application on a different port.** Not a branch inside the console's routes: a
separate ASGI app with two routes, mounted on its own bind, importing neither `observe` nor
`peer`. A conditional that decides whether a request may see the board is a conditional that can
be got wrong; a program that cannot reach the board from here cannot be got wrong that way. A test
asserts those imports are absent.

**It shows the thought and nothing around it.** Summary, text, state, date. Not the project, not
the branch, not the session's generated title, not the drafts, and never a block. The context an
idea carries is what makes it legible to its owner a week later, and it is also a list of what
that person was working on — including work a teammate has no business seeing. That was a
disclosure decision, made once, deliberately (docs/07-security.md).

**Everything it renders is scrubbed on the way out.** The store keeps a human's own words verbatim
because losing the thought to a filter would be the tool failing at its job; a viewer who is not
that human gets the filtered version. The rule reads "any surface a second person can open
redacts before it renders" and this is that surface.

**It has no JavaScript.** A plain form and a plain list, because the person opening it is on an
unknown device and is not here to debug a console.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from agent_desk.ideas import inbox
from agent_desk.store.redact import scrub
from agent_desk.store.repo import Store, Viewer
from agent_desk.web.origin import SameOriginOnly

TEMPLATES = Path(__file__).parent / "templates" / "shared"

# An idea is a sentence somebody typed. Sixteen kilobytes is generous for that, and small enough
# that a link holder cannot exhaust the owner's memory with one post or their disk with a hundred.
MAX_SUBMISSION_BYTES = 16 * 1024

# Its own loader, rooted in its own directory: an owner fragment is not merely unused here, it is
# unreachable.
env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

log = structlog.get_logger("agent_desk.shared")


def _when(created_at: int) -> str:
    """A date a person reads, from the milliseconds this program stores."""
    return datetime.fromtimestamp(created_at / 1000, tz=UTC).strftime("%d %b %Y")


# `redirect_slashes=False`: that redirect echoes the request's own Host header back into an
# absolute Location, and this bind answers to whatever hostname is pointed at it.
app = FastAPI(title="agent-desk · ideas", openapi_url=None, redirect_slashes=False)
# The same guard as the console's. A viewer's token is not a secret a foreign page has, but
# a page that obtained one must not be able to post through the viewer's browser either.
app.add_middleware(SameOriginOnly)


def _store(request: Request) -> Store | None:
    """The store the console opened, if it has. This application never opens or closes it.

    Both halves matter. The two servers start together, so on the way up this is a store that
    exists and is not open yet; on the way down the console closes it while this bind is still
    draining. Either way a viewer gets the answer a wrong link gets.
    """
    store = getattr(request.app.state, "store", None)
    return store if isinstance(store, Store) and store.opened else None


async def _viewer(request: Request, token: str) -> tuple[Store, Viewer] | None:
    store = _store(request)
    if store is None:  # pragma: no cover - the console opens it at startup
        return None
    viewer = await store.viewer_for(token)
    return None if viewer is None else (store, viewer)


@app.get("/shared/{token}", response_class=HTMLResponse)
async def ideas_page(token: str, request: Request) -> Response:
    """The list, and the box. Nothing here can reach the board or a session."""
    found = await _viewer(request, token)
    if found is None:
        # The same answer for a wrong token, a revoked one and a missing store: a viewer learns
        # whether their own link works, and nothing else.
        return HTMLResponse(env.get_template("gone.html").render(), status_code=404)

    store, viewer = found
    ideas = await store.ideas()
    # Names and counts, never the thought itself: the log answers "who could see this, and when"
    # (docs/07-security.md), and it is not a second copy of the inbox.
    log.info("shared view opened", viewer=viewer.name, ideas=len(ideas))
    return HTMLResponse(
        env.get_template("page.html").render(
            viewer=viewer.name,
            token=token,
            ideas=[
                {
                    "summary": scrub(idea.summary),
                    "text": scrub(idea.text),
                    "state": idea.state,
                    "when": _when(idea.created_at),
                }
                for idea in ideas
            ],
        )
    )


@app.post("/shared/{token}/idea")
async def submit_idea(token: str, request: Request) -> Response:
    """The other half of problem 5: a box to put an idea in.

    It writes one row into this program's own store and touches nothing else — no session, no
    repository, no board. Who sent it is recorded as the source, because an idea whose author is
    unknown is an idea nobody can ask about (docs/05-ideas.md).
    """
    found = await _viewer(request, token)
    if found is None:
        return HTMLResponse(env.get_template("gone.html").render(), status_code=404)

    store, viewer = found
    if int(request.headers.get("content-length") or 0) > MAX_SUBMISSION_BYTES:
        # Refused before it is read. A link holder is authenticated, not trusted with the owner's
        # memory and disk — "the token is unguessable" is an argument about who gets in, not about
        # what they may do once they are.
        return HTMLResponse(env.get_template("gone.html").render(), status_code=413)

    body = (await request.body()).decode("utf-8", errors="replace")
    text = (parse_qs(body, keep_blank_values=True).get("text", [""])[0] or "").strip()
    if text:
        await inbox.capture(
            store,
            text,
            source_kind="typed",
            context={"from": viewer.name},
        )
        log.info("shared idea captured", viewer=viewer.name, chars=len(text))

    # A redirect rather than a rendered response, so a refresh does not submit again.
    return RedirectResponse(f"/shared/{token}", status_code=303)
