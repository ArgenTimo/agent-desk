"""The console's routes: the board, the input field, the inbox, the viewers, and the one write path.

Written when this was a read-only board and left saying so for three phases, which is the failure
mode CLAUDE.md names — a document that describes what a module used to be is worse than no
document, because it is read and believed. What is actually here: nine routes that change state,
a store, model calls behind two of them, and the single import of `peer` that docs/adr/0002
permits to exist in `web/` and nowhere else.

The ordering is the part worth reading twice. A board sorted by `updatedAt` puts a session that
flickered between `idle` and `busy` above a long healthy run, which is exactly backwards for a
surface whose job is triage (docs/06-console.md).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from agent_desk import peer
from agent_desk.config import settings
from agent_desk.observe import registry, transcript
from agent_desk.observe.model import (
    AttentionHint,
    Session,
    TranscriptTail,
    attention_hint,
    now_ms,
    since,
    triage_rank,
)
from agent_desk.store.repo import DRAFT_KINDS, Store
from agent_desk.web import blocks as block_runs

router = APIRouter()

log = structlog.get_logger("agent_desk.web")

# A minted token, waiting for the one render that shows it. Memory only and popped on read: the
# store keeps a hash, and this keeps nothing a second time.
JUST_MINTED: dict[str, str] = {}

# One process, one SQLite file (docs/adr/0003). The instance is opened by the application's
# lifespan and replaced wholesale by a test that wants its own.
store = Store(settings.db_path)

TEMPLATES = Path(__file__).parent / "templates"


def _ago(then_ms: int, now: int | None = None) -> str:
    """How long since anything changed.

    Under a minute the board says "just now" rather than counting seconds. The reason is not
    taste: the fragment is diffed to decide whether to push it, so a per-second number would
    re-render the page every second — losing a text selection, and re-fetching whatever row the
    reader had open, all day.
    """
    now = now if now is not None else now_ms()
    if now - then_ms < 60_000:
        return "just now"
    return f"{since(then_ms, now)} ago"


def _clock(entry_at: object) -> str:
    """A wall-clock time for a transcript entry, or nothing when it carried none."""
    return entry_at.strftime("%H:%M") if hasattr(entry_at, "strftime") else ""


env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html"]),
    # A name the template asks for and the route did not pass raises here instead of rendering an
    # empty string. The default cost a whole page once: `const silence = {{ poll }} * 3` became
    # `const silence =  * 3`, a syntax error that killed every script on the board — a page frozen
    # at first paint, and a green test suite. Loud beats plausible, which is the argument of
    # docs/adr/0004 applied one layer up.
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
env.filters["ago"] = _ago
env.filters["clock"] = _clock


@dataclass(frozen=True)
class BoardRow:
    """One session, everything known about it, and the one thing merely inferred."""

    session: Session
    tail: TranscriptTail | None
    hint: AttentionHint


def board() -> tuple[list[BoardRow], list[str]]:
    """Read the registry, then the tail of each live session. Blocking; call it in a thread."""
    read = registry.read_registry()
    now = now_ms()
    rows: list[BoardRow] = []
    for session in read.sessions:
        tail = transcript.read_tail(session.session_id)
        hint = attention_hint(session, tail, now=now, after_seconds=settings.idle_hint_seconds)
        rows.append(BoardRow(session=session, tail=tail, hint=hint))
    # Triage first; within a group, most recent movement first, and the name to keep the order
    # stable between two ticks that are otherwise identical.
    rows.sort(key=lambda r: (triage_rank(r.session, r.hint), -r.session.updated_at, r.session.name))
    return rows, read.notices


def render_board() -> str:
    """The fragment the page holds and every server-sent event replaces."""
    rows, notices = board()
    return env.get_template("_board.html").render(rows=rows, notices=notices)


def render_tail(session_id: str) -> str:
    """The drill-down: the tail of one transcript, and nothing else (docs/06-console.md)."""
    tail = transcript.read_tail(session_id)
    return env.get_template("_tail.html").render(tail=tail)


async def render_blocks() -> str:
    """The column under the input field: newest first, each showing its state and its thread."""
    rows = await store.blocks()
    open_threads = await store.open_threads()
    known = {thread.id for thread in open_threads}
    # A block's own thread is always an option, even when it has fallen outside the bound. Without
    # this the select rendered with nothing selected, the browser picked the first entry — the
    # newest subject — and the ↵ button posted *that*: the control for correcting a misfile made
    # one, silently, and logged it as a human decision.
    missing = [
        thread
        for thread in await store.threads_of({row.thread_id for row in rows} - known)
        if thread.id not in known
    ]
    ideas = {idea.block_id: idea for idea in await store.ideas() if idea.block_id}
    return env.get_template("_blocks.html").render(
        blocks=rows,
        open_threads=open_threads + missing,
        threads_by_id={thread.id: thread for thread in open_threads + missing},
        ideas=ideas,
        partial=block_runs.PARTIAL,
    )


def render_message(stage: str, session_id: str, text: str = "", detail: str = "") -> str:
    """The one write path's surface: compose, confirm, and what happened.

    Rendered outside the board on purpose. The board replaces itself whenever it changes, and a
    panel inside it would vanish under a half-typed message every time a session went idle.
    """
    rows, _ = board()
    row = next((r for r in rows if r.session.session_id == session_id), None)
    return env.get_template("_message.html").render(
        stage=stage if row is not None else "gone", row=row, text=text, detail=detail
    )


async def render_inbox() -> str:
    """Kept ideas, each carrying where it came from (docs/05-ideas.md)."""
    ideas = await store.ideas()
    drafts = {idea.id: await store.drafts_for(idea.id) for idea in ideas}
    return env.get_template("_inbox.html").render(
        ideas=ideas,
        drafts=drafts,
        drafting={idea_id for idea_id, _ in block_runs.DRAFTING},
    )


@router.get("/", response_class=HTMLResponse)
async def page() -> HTMLResponse:
    return HTMLResponse(await render_page())


@router.get("/sessions/{session_id}/tail", response_class=HTMLResponse)
async def session_tail(session_id: str) -> HTMLResponse:
    """A row expands to the tail of its transcript. That is the whole drill-down in v1."""
    return HTMLResponse(await asyncio.to_thread(render_tail, session_id))


def _wants_fragment(request: Request) -> bool:
    """Did htmx ask for this, or did a browser submit a form?

    Every action in this console is a real form with a real action, and htmx — when it is there —
    upgrades it into an in-place swap. When it is not, the same route answers with a whole page.
    The console is server-rendered either way (docs/adr/0003); what the library adds is that the
    page does not blink, and a tool that cannot be used without it would have the dependency the
    wrong way round.
    """
    return request.headers.get("hx-request") == "true"


async def render_page(message: str = "") -> str:
    """The whole console: the board, the write-path panel when one is open, and the blocks."""
    return env.get_template("board.html").render(
        board=await asyncio.to_thread(render_board),
        message=message,
        blocks=await render_blocks(),
        poll=settings.registry_poll_seconds,
    )


async def _form(request: Request) -> dict[str, str]:
    """One urlencoded form, parsed with the standard library.

    Starlette's own `request.form()` asserts that `python-multipart` is installed before it will
    read even an `application/x-www-form-urlencoded` body — and every form in this console carries
    one or two short fields and none of them will ever accept a file. Three lines of `urllib`
    against a dependency in the lock file forever is not a close call (CLAUDE.md, "Simplicity
    first"; the deliberately-absent list in pyproject.toml is the same argument).
    """
    body = (await request.body()).decode("utf-8", errors="replace")
    return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}


@router.get("/viewers", response_class=HTMLResponse)
async def viewers_page(shown: str = "") -> HTMLResponse:
    """Who may open the shared ideas list, and until when (docs/07-security.md, Phase 4).

    Owner-only, like everything else on this bind. `shown` is a viewer id, not a token: the token
    itself is handed over once, out of a slot in memory that this render empties. It never appears
    in a URL, which is where browser history, the referer of the next request and any log that
    records a path would all have kept it.
    """
    token = JUST_MINTED.pop(shown, "") if shown else ""
    viewers = await store.viewers()
    return HTMLResponse(
        env.get_template("viewers.html").render(
            viewers=viewers,
            minted=token,
            minted_for=next((v.name for v in viewers if v.id == shown), ""),
            share_host=settings.share_host,
            share_port=settings.share_port,
        )
    )


@router.post("/viewers", response_class=HTMLResponse)
async def mint_viewer(request: Request) -> Response:
    """Mint one named link. The name is the whole identity, so it is required."""
    name = (await _form(request)).get("name", "").strip()
    if not name:
        return RedirectResponse("/viewers", status_code=303)

    viewer, token = await store.create_viewer(name)
    log.info("viewer link minted", viewer=name)
    # The token goes into a one-shot slot in memory and the browser is redirected to an id, not to
    # a secret. Rendering it directly kept the token out of the URL but lost post/redirect/get, so
    # a refresh minted a second credential for the same person — two links to revoke instead of
    # one. A viewer id in a query string is not a secret; the token never appears in one.
    JUST_MINTED[viewer.id] = token
    return RedirectResponse(f"/viewers?shown={viewer.id}", status_code=303)


@router.post("/viewers/{viewer_id}/revoke", response_class=HTMLResponse)
async def revoke_viewer(viewer_id: str) -> Response:
    """Revocation is a timestamp, not a delete: an audit asks "until when"."""
    await store.revoke_viewer(viewer_id)
    log.info("viewer link revoked", viewer_id=viewer_id)
    return RedirectResponse("/viewers", status_code=303)


@router.get("/sessions/{session_id}/message", response_class=HTMLResponse)
async def compose_message(session_id: str, request: Request) -> Response:
    """Open the compose panel for one named session. Nothing is sent by opening it."""
    panel = await asyncio.to_thread(render_message, "compose", session_id)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/sessions/{session_id}/message/review", response_class=HTMLResponse)
async def review_message(session_id: str, request: Request) -> Response:
    """Show it in full, against the name of the session it would go to (docs/adr/0002).

    This step exists because the cost of the next one is somebody else's context. It is not a
    confirmation dialog in the "are you sure" sense — it is the message, rendered as it would
    arrive, beside the session that would receive it.
    """
    text = (await _form(request)).get("text", "").strip()
    stage = "confirm" if text else "compose"
    panel = await asyncio.to_thread(render_message, stage, session_id, text)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    # Rendered rather than redirected: reviewing has no side effect, and the message must survive
    # the round trip to be read in full — which is the whole point of the step.
    return HTMLResponse(await render_page(panel))


@router.post("/sessions/{session_id}/message/send", response_class=HTMLResponse)
async def send_message(session_id: str, request: Request) -> Response:
    """The click. It reaches `peer.send` and reports exactly what came back."""
    text = (await _form(request)).get("text", "").strip()
    rows, _ = await asyncio.to_thread(board)
    row = next((r for r in rows if r.session.session_id == session_id), None)
    if row is None or not text:
        panel = await asyncio.to_thread(render_message, "gone", session_id)
        return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))

    delivery = peer.send(row.session, text)
    stage = "delivered" if delivery.delivered else "refused"
    panel = await asyncio.to_thread(render_message, stage, session_id, text, delivery.detail)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    # Two things this route owes the day `peer.send` actually delivers, and they close together.
    # A redirect instead of a render: a refresh here would send the message twice, and twice into
    # somebody's context is the failure adr/0002 is about. And a precondition rather than a
    # template — nothing today stops a post going straight to /send without /review, which is
    # harmless while the answer is a refusal and is not the "shown in full first" that adr/0002
    # describes.
    return HTMLResponse(await render_page(panel))


@router.post("/blocks", response_class=HTMLResponse)
async def ask(request: Request) -> Response:
    """One line of input, accepted and answered on its own time.

    The response is the column, and the field is cleared by the page the moment this returns —
    submitting frees it, and nothing here waits for an answer (docs/04-threads-and-blocks.md).
    """
    typed = (await _form(request)).get("text", "").strip()
    if typed:
        rows, _ = await asyncio.to_thread(board)
        await block_runs.submit(store, typed, rows)
    if _wants_fragment(request):
        return HTMLResponse(await render_blocks())
    # Post/redirect/get: a refresh after asking must not ask again.
    return RedirectResponse("/", status_code=303)


@router.get("/blocks", response_class=HTMLResponse)
async def block_column() -> HTMLResponse:
    return HTMLResponse(await render_blocks())


@router.post("/blocks/{block_id}/retry", response_class=HTMLResponse)
async def retry_block(block_id: str, request: Request) -> Response:
    """A block that failed does not disappear; it offers this (docs/04)."""
    block = await store.block(block_id)
    if block is not None and block.state in ("failed", "cancelled"):
        rows, _ = await asyncio.to_thread(board)
        await block_runs.retry(store, block, rows)
    if _wants_fragment(request):
        return HTMLResponse(await render_blocks())
    return RedirectResponse("/", status_code=303)


@router.post("/ideas/{idea_id}/{action}", response_class=HTMLResponse)
async def idea_action(idea_id: str, action: str, request: Request) -> Response:
    """Keep, discard, edit the summary, or produce one of the three drafts (docs/05-ideas.md).

    Nothing here writes outside this program's own store. That is the rule the ideas page exists
    for, and the corollary is explicit: an action that writes elsewhere is an ADR, not a commit.
    """
    idea = await store.idea(idea_id)
    if idea is None:
        return HTMLResponse(await render_inbox(), status_code=404)

    form = await _form(request)
    if action not in ("keep", "drop", "summary", *DRAFT_KINDS):
        # An action this program does not have is a mistake somewhere, not something to redirect
        # away from quietly — that is how a typo becomes a mystery.
        # The segment is not echoed back: reflecting an unvalidated path into a response is a
        # habit worth not having, even where the content type makes it harmless.
        return PlainTextResponse("no such action", status_code=404)

    # The templates hide a button that does not apply; the route has to mean it. Keeping an idea
    # that was already promoted quietly walked it backwards through its own four states.
    allowed = {
        "new": {"keep", "drop", "summary"},
        "kept": {"drop", "summary", *DRAFT_KINDS},
        "promoted": {"summary", *DRAFT_KINDS},
        "dropped": {"keep", "summary"},
    }[idea.state]
    if action not in allowed:
        return PlainTextResponse(f"an idea that is {idea.state} cannot do that", status_code=409)

    if action in ("keep", "drop"):
        await store.set_idea_state(idea_id, "kept" if action == "keep" else "dropped")
    elif action == "summary":
        summary = form.get("summary", "").strip()
        if summary:
            await store.set_idea_summary(idea_id, summary)
    elif action in DRAFT_KINDS:
        # The tuple and the Literal are defined together in the store, so a route validating a
        # path segment and the type describing it cannot drift apart — and the membership test
        # narrows the string for free.
        await block_runs.draft(store, idea, action)
        await store.set_idea_state(idea_id, "promoted")

    # A form field, not a header: the card must behave the same with htmx and without it, and
    # `hx-headers` only travels when htmx is the one sending.
    from_the_card = form.get("from") == "card"
    if _wants_fragment(request):
        return HTMLResponse(await render_blocks() if from_the_card else await render_inbox())
    return RedirectResponse("/" if from_the_card else "/ideas", status_code=303)


@router.get("/ideas", response_class=HTMLResponse)
async def inbox_page() -> HTMLResponse:
    return HTMLResponse(env.get_template("inbox.html").render(inbox=await render_inbox()))


@router.get("/ideas/list", response_class=HTMLResponse)
async def inbox_list() -> HTMLResponse:
    return HTMLResponse(await render_inbox())


@router.post("/blocks/{block_id}/thread", response_class=HTMLResponse)
async def set_block_thread(block_id: str, request: Request) -> Response:
    """Correcting a misfile costs one click, and the block re-runs against the right context."""
    block = await store.block(block_id)
    if block is not None:
        chosen = (await _form(request)).get("thread_id", "").strip()
        rows, _ = await asyncio.to_thread(board)
        await block_runs.set_thread(store, block, chosen or None, rows)
    if _wants_fragment(request):
        return HTMLResponse(await render_blocks())
    return RedirectResponse("/", status_code=303)


@router.post("/blocks/{block_id}/cancel", response_class=HTMLResponse)
async def cancel_block(block_id: str, request: Request) -> Response:
    """Stop a run that is no longer worth waiting for. The block stays, saying it was cancelled."""
    await block_runs.cancel(store, block_id)
    if _wants_fragment(request):
        return HTMLResponse(await render_blocks())
    return RedirectResponse("/", status_code=303)
