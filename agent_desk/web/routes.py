"""The board: what every session is doing, without opening a terminal.

Everything here is read-only. There is no form, no store and no model call in this phase; the one
write path of docs/adr/0002 does not exist yet and this module does not import it.

The ordering is the part worth reading twice. A board sorted by `updatedAt` puts a session that
flickered between `idle` and `busy` above a long healthy run, which is exactly backwards for a
surface whose job is triage (docs/06-console.md).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

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
from agent_desk.store.repo import Store
from agent_desk.web import blocks as block_runs

router = APIRouter()

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
    threads = {thread.id: thread for thread in await store.open_threads()}
    return env.get_template("_blocks.html").render(
        blocks=rows, threads=threads, partial=block_runs.PARTIAL
    )


@router.get("/", response_class=HTMLResponse)
async def page() -> HTMLResponse:
    board_html = await asyncio.to_thread(render_board)
    return HTMLResponse(
        env.get_template("board.html").render(
            board=board_html,
            blocks=await render_blocks(),
            poll=settings.registry_poll_seconds,
        )
    )


@router.get("/sessions/{session_id}/tail", response_class=HTMLResponse)
async def session_tail(session_id: str) -> HTMLResponse:
    """A row expands to the tail of its transcript. That is the whole drill-down in v1."""
    return HTMLResponse(await asyncio.to_thread(render_tail, session_id))


@router.post("/blocks", response_class=HTMLResponse)
async def ask(request: Request) -> HTMLResponse:
    """One line of input, accepted and answered on its own time.

    The response is the column, and the field is cleared by the page the moment this returns —
    submitting frees it, and nothing here waits for an answer (docs/04-threads-and-blocks.md).
    """
    form = await request.form()
    typed = str(form.get("text") or "").strip()
    if typed:
        rows, _ = await asyncio.to_thread(board)
        await block_runs.submit(store, typed, rows)
    return HTMLResponse(await render_blocks())


@router.get("/blocks", response_class=HTMLResponse)
async def block_column() -> HTMLResponse:
    return HTMLResponse(await render_blocks())


@router.post("/blocks/{block_id}/retry", response_class=HTMLResponse)
async def retry_block(block_id: str) -> HTMLResponse:
    """A block that failed does not disappear; it offers this (docs/04)."""
    block = await store.block(block_id)
    if block is not None and block.state in ("failed", "cancelled"):
        rows, _ = await asyncio.to_thread(board)
        await block_runs.retry(store, block, rows)
    return HTMLResponse(await render_blocks())


@router.post("/blocks/{block_id}/cancel", response_class=HTMLResponse)
async def cancel_block(block_id: str) -> HTMLResponse:
    """Stop a run that is no longer worth waiting for. The block stays, saying it was cancelled."""
    block_runs.cancel(block_id)
    return HTMLResponse(await render_blocks())
