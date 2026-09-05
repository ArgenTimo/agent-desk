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
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import parse_qs

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup, escape

from agent_desk import dispatch, peer, tracker
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
from agent_desk.observe.shape import repository_of
from agent_desk.store.repo import DRAFT_KINDS, Group, Idea, Store, Thread
from agent_desk.web import autostart
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


def _prose(text: str) -> Markup:
    """An answer, as the model actually writes it.

    The prompt asks for plain sentences and mostly gets them, but a model reaches for `**` and
    backticks the way anybody does, and printing those characters at a reader is the tool showing
    its own plumbing. Two marks are turned into the thing they mean and nothing else is: this is
    not a markdown renderer, and the escape happens first, so what is added here is the only
    markup that can reach the page.
    """
    out = str(escape(text))
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out, flags=re.S)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return Markup(out)


# The registry's three words, said the way somebody who does not use a terminal would say them.
# The word itself stays on the tooltip: this renders a fact, it does not replace one.
PLAINLY = {"busy": "working", "idle": "idle", "shell": "running a command"}


def _plainly(status: str) -> str:
    return PLAINLY.get(status, status)


env.filters["plainly"] = _plainly
env.filters["prose"] = _prose
env.filters["ago"] = _ago
env.filters["clock"] = _clock


@dataclass(frozen=True)
class BoardRow:
    """One session, everything known about it, and the one thing merely inferred."""

    session: Session
    tail: TranscriptTail | None
    hint: AttentionHint
    # Which card this row sits under, so that a question aimed at one can find its sessions
    # without the shape being rebuilt to answer the question.
    project_key: str = ""
    project_name: str = ""


@dataclass(frozen=True)
class Instance:
    """One working directory, and the consoles open in it."""

    path: str
    name: str
    rows: list[BoardRow]

    @property
    def busy(self) -> int:
        return sum(1 for row in self.rows if row.session.status == "busy")

    @property
    def flagged(self) -> int:
        return sum(1 for row in self.rows if row.hint.waiting)


@dataclass(frozen=True)
class Project:
    """One repository, or several that a human said were one thing."""

    key: str
    name: str
    instances: list[Instance]
    group_id: str | None = None
    repo_keys: tuple[str, ...] = ()

    @property
    def sessions(self) -> int:
        return sum(len(instance.rows) for instance in self.instances)

    @property
    def flagged(self) -> int:
        return sum(instance.flagged for instance in self.instances)


def shape(rows: list[BoardRow], groups: list[Group]) -> list[Project]:
    """Fold the flat list of sessions into what a person actually has.

    Sessions belong to a working directory, directories belong to a repository, and repositories
    belong to a project — which is the repository itself unless somebody said otherwise. Nothing
    is declared that can be derived: a level that had to be maintained by hand would be wrong the
    first time somebody forgot (docs/adr/0004, about a different file, for the same reason).

    The order is the board's order: whoever needs a human first.
    """
    by_directory: dict[str, list[BoardRow]] = {}
    for row in rows:
        by_directory.setdefault(row.session.cwd, []).append(row)

    instances = [
        Instance(path=path, name=Path(path).name or path, rows=rows_here)
        for path, rows_here in by_directory.items()
    ]
    repos = {instance.path: repository_of(instance.path) for instance in instances}

    claimed = {key: group for group in groups for key in group.repo_keys}
    buckets: dict[str, list[Instance]] = {}
    labels: dict[str, tuple[str, str | None, tuple[str, ...]]] = {}
    for instance in instances:
        repo = repos[instance.path]
        group = claimed.get(repo.key)
        bucket = group.id if group else repo.key
        buckets.setdefault(bucket, []).append(instance)
        labels[bucket] = (
            (group.name, group.id, tuple(group.repo_keys))
            if group
            else (repo.name, None, (repo.key,))
        )

    projects = []
    for bucket, held in buckets.items():
        name, group_id, keys = labels[bucket]
        # Stamped here rather than looked up later: a question aimed at a card has to find its
        # sessions, and rebuilding the shape to answer that would be a second chance to disagree
        # with the board the human is looking at.
        stamped = [
            Instance(
                path=instance.path,
                name=instance.name,
                rows=[replace(row, project_key=bucket, project_name=name) for row in instance.rows],
            )
            for instance in held
        ]
        projects.append(
            Project(key=bucket, name=name, instances=stamped, group_id=group_id, repo_keys=keys)
        )
    # A project is as urgent as its most urgent session, and the rows arrive in that order. The
    # position is looked up by session id rather than by the row object, because stamping made new
    # objects — which is the kind of thing that fails loudly once and quietly ever after.
    # A project somebody has just declared has no members yet, and it still has to appear — the
    # button that made it exists to produce a place to drag cards into. An empty one sorts last,
    # after everything that is actually running.
    for group in groups:
        if group.id not in buckets:
            projects.append(
                Project(
                    key=group.id,
                    name=group.name,
                    instances=[],
                    group_id=group.id,
                    repo_keys=tuple(group.repo_keys),
                )
            )

    position = {row.session.session_id: index for index, row in enumerate(rows)}
    projects.sort(
        key=lambda project: min(
            (
                position[row.session.session_id]
                for instance in project.instances
                for row in instance.rows
            ),
            default=len(rows),
        )
    )
    return projects


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


def render_board(groups: list[Group] | None = None) -> str:
    """The fragment the page holds and every server-sent event replaces."""
    rows, notices = board()
    projects = shape(rows, groups or [])
    return env.get_template("_board.html").render(
        rows=rows,
        projects=projects,
        notices=notices,
        flagged=sum(1 for row in rows if row.hint.waiting),
    )


def render_card(kind: str, card_id: str, groups: list[Group] | None = None) -> str:
    """What a card actually contains, for when somebody opens one or drags it into the middle.

    This is where the detail the left column deliberately does not show lives: the branch, what a
    session last did, what it farmed out, and whether this program thinks it may want somebody. A
    tree that said all of that about every session would be a tree nobody reads
    (docs/06-console.md), and a tree that said none of it anywhere would be a board you still
    have to open a terminal to use.
    """
    rows, _ = board()
    projects = shape(rows, groups or [])
    stamped = [row for project in projects for i in project.instances for row in i.rows]

    if kind in ("session", "agent"):
        chosen = [row for row in stamped if row.session.session_id == card_id]
    elif kind == "instance":
        chosen = [row for row in stamped if row.session.cwd == card_id]
    elif kind == "project":
        chosen = [row for row in stamped if row.project_key == card_id]
    else:
        return ""
    return env.get_template("_card.html").render(kind=kind, rows=chosen, card_id=card_id)


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
    # One message can hold several thoughts, so a block's card is a list rather than a card
    # (docs/05-ideas.md).
    ideas: dict[str, list[Idea]] = {}
    for idea in reversed(await store.ideas()):
        if idea.block_id:
            ideas.setdefault(idea.block_id, []).append(idea)
    directives = {d.block_id: d for d in await store.directives()}
    return env.get_template("_blocks.html").render(
        blocks=rows,
        drafted=await store.drafted("ticket"),
        filings={filing.idea_id: filing for filing in await store.filings()},
        open_threads=open_threads + missing,
        threads_by_id={thread.id: thread for thread in open_threads + missing},
        ideas=ideas,
        directives=directives,
        partial=block_runs.PARTIAL,
    )


def render_message(
    stage: str, session_id: str, text: str = "", detail: str = "", directive_id: str = ""
) -> str:
    """The one write path's surface: compose, confirm, and what happened.

    Rendered outside the board on purpose. The board replaces itself whenever it changes, and a
    panel inside it would vanish under a half-typed message every time a session went idle.
    """
    rows, _ = board()
    row = next((r for r in rows if r.session.session_id == session_id), None)
    return env.get_template("_message.html").render(
        stage=stage if row is not None else "gone",
        row=row,
        text=text,
        detail=detail,
        directive_id=directive_id,
    )


async def render_ideas() -> str:
    """The bottom half of the right column: what has been written down.

    Dropped ideas are not shown here. The inbox keeps them — an idea's history is part of what the
    notebook is for — but a column somebody glances at is about what is still live.
    """
    ideas = [idea for idea in await store.ideas() if idea.state != "dropped"]
    known = {idea.id for idea in ideas}
    children: dict[str, list[Idea]] = {idea.id: [] for idea in ideas}
    roots: list[Idea] = []
    for idea in reversed(ideas):  # oldest first inside a group, which is the order they arrived
        # A child whose parent was discarded is shown at the top rather than hidden under a card
        # nobody can see: an idea that vanished from the inbox is the one failure here.
        if idea.parent_id in known:
            children[idea.parent_id].append(idea)
        else:
            roots.append(idea)
    return env.get_template("_ideas.html").render(
        roots=list(reversed(roots)),
        children=children,
        counted=len(ideas),
        drafted=await store.drafted("ticket"),
        filings={filing.idea_id: filing for filing in await store.filings()},
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


async def open_chats() -> list[Thread]:
    """The tabs across the top of the middle column.

    One by default and always at least one: an interaction area with no tab has nowhere to put an
    answer, and a page that renders zero of them would make the `+` the only way to start.
    """
    threads = await store.open_threads()
    if not threads:
        threads = [await store.create_thread("chat 1")]
    # Oldest first, so a tab keeps its place as new ones are added to the right of it.
    return list(reversed(threads))


async def render_page(message: str = "") -> str:
    """The whole console: the board, the write-path panel when one is open, and the blocks.

    The board is read once and used twice — as the rendered cards, and as the list the question
    field offers when you point a question at a project or a session.
    """
    groups = await store.groups()
    rows, notices = await asyncio.to_thread(board)
    projects = shape(rows, groups)
    return env.get_template("board.html").render(
        threads=await open_chats(),
        ideas=await render_ideas(),
        board=env.get_template("_board.html").render(
            rows=rows,
            projects=projects,
            notices=notices,
            flagged=sum(1 for row in rows if row.hint.waiting),
        ),
        projects=projects,
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


@router.post("/threads", response_class=HTMLResponse)
async def new_thread(request: Request) -> Response:
    """`+` on the tab bar. A new chat is empty, which is what an interaction area should be."""
    await store.create_thread(f"chat {len(await store.open_threads()) + 1}")
    if _wants_fragment(request):
        return HTMLResponse(env.get_template("_tabs.html").render(threads=await open_chats()))
    return RedirectResponse("/", status_code=303)


@router.post("/threads/{thread_id}/close", response_class=HTMLResponse)
async def close_thread(thread_id: str, request: Request) -> Response:
    """`×` on a tab. Closing is not deleting: the subject is marked closed and everything asked in
    it stays in the store, because a question that vanished is a question you ask again
    (docs/04-threads-and-blocks.md)."""
    if len(await store.open_threads()) > 1:
        await store.close_thread(thread_id)
    if _wants_fragment(request):
        return HTMLResponse(env.get_template("_tabs.html").render(threads=await open_chats()))
    return RedirectResponse("/", status_code=303)


@router.get("/cards/{kind}", response_class=HTMLResponse)
async def card(kind: str, id: str = "") -> HTMLResponse:
    """What one card contains. The id is a query parameter because two of the kinds are identified
    by a filesystem path, and a path does not fit in a path segment."""
    if kind == "idea":
        # An idea is not a session and has no board row: what it contains is what was written.
        idea = await store.idea(id)
        return HTMLResponse(
            env.get_template("_card_idea.html").render(idea=idea),
            status_code=200 if idea else 404,
        )
    groups = await store.groups()
    markup = await asyncio.to_thread(render_card, kind, id, groups)
    return HTMLResponse(markup, status_code=200 if markup else 404)


async def render_project(key: str) -> str:
    """The settings panel for one project, rendered where the write path's panel goes."""
    rows, _ = await asyncio.to_thread(board)
    projects = shape(rows, await store.groups())
    named = next((project for project in projects if project.key == key), None)
    return env.get_template("_project.html").render(
        key=key,
        name=named.name if named else key,
        links=await store.links(key),
        tasks=await store.tasks(repo_key=key),
        arming=await store.autostart(key),
        # The console says exactly what the loop decided, because it asks the same function.
        why_not=await autostart.why_not(store, key),
    )


@router.get("/project-settings", response_class=HTMLResponse)
async def project_settings(request: Request, key: str = "") -> Response:
    """The `⋯` on a project card. A repository key holds slashes and colons, so it travels as a
    query parameter rather than as a path segment."""
    panel = await render_project(key)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/project-links", response_class=HTMLResponse)
async def add_project_link(request: Request) -> Response:
    """Somewhere this project also lives. The token field names a variable, never a value."""
    form = await _form(request)
    key = form.get("key", "").strip()
    name = form.get("name", "").strip()[:40]
    url = form.get("url", "").strip()
    if key and name and url.startswith(("http://", "https://")):
        await store.set_link(
            repo_key=key, name=name, url=url, token_env=form.get("token_env", "").strip()[:64]
        )
    panel = await render_project(key)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/project-links/remove", response_class=HTMLResponse)
async def remove_project_link(request: Request) -> Response:
    form = await _form(request)
    key = form.get("key", "").strip()
    await store.remove_link(key, form.get("name", "").strip())
    panel = await render_project(key)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/projects", response_class=HTMLResponse)
async def create_project(request: Request) -> Response:
    """Declare a project that is more than one repository.

    The default needs no button: every checkout of one origin is already one project. This is for
    the case the default cannot know — an API and an app in two repositories that are obviously
    one product.
    """
    form = await _form(request)
    name = form.get("name", "").strip()
    if name:
        group = await store.create_group(name)
        log.info("project declared", project=group.name)
        # A project declared by dropping one card onto another arrives with its first member.
        first = form.get("repo_key", "").strip()
        if first:
            await store.add_to_group(group.id, first)
        if _wants_fragment(request):
            return HTMLResponse(await asyncio.to_thread(render_board, await store.groups()))
    return RedirectResponse("/", status_code=303)


@router.post("/projects/{group_id}/members", response_class=HTMLResponse)
async def add_to_project(group_id: str, request: Request) -> Response:
    """What a card dropped onto a project card does."""
    repo_key = (await _form(request)).get("repo_key", "").strip()
    if repo_key:
        await store.add_to_group(group_id, repo_key)
    if _wants_fragment(request):
        return HTMLResponse(await asyncio.to_thread(render_board, await store.groups()))
    return RedirectResponse("/", status_code=303)


@router.post("/projects/{group_id}/dissolve", response_class=HTMLResponse)
async def dissolve_project(group_id: str, request: Request) -> Response:
    """Ungrouping returns every repository in it to being its own project. Nothing is lost."""
    await store.delete_group(group_id)
    if _wants_fragment(request):
        return HTMLResponse(await asyncio.to_thread(render_board, await store.groups()))
    return RedirectResponse("/", status_code=303)


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
    form = await _form(request)
    text = form.get("text", "").strip()
    stage = "confirm" if text else "compose"
    panel = await asyncio.to_thread(
        render_message, stage, session_id, text, "", form.get("directive", "").strip()
    )
    if _wants_fragment(request):
        return HTMLResponse(panel)
    # Rendered rather than redirected: reviewing has no side effect, and the message must survive
    # the round trip to be read in full — which is the whole point of the step.
    return HTMLResponse(await render_page(panel))


@router.post("/sessions/{session_id}/message/send", response_class=HTMLResponse)
async def send_message(session_id: str, request: Request) -> Response:
    """The click. It reaches `peer.send` and reports exactly what came back."""
    form = await _form(request)
    text = form.get("text", "").strip()
    directive_id = form.get("directive", "").strip()
    rows, _ = await asyncio.to_thread(board)
    row = next((r for r in rows if r.session.session_id == session_id), None)
    if row is None or not text:
        panel = await asyncio.to_thread(render_message, "gone", session_id)
        return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))

    delivery = peer.send(row.session, text)
    stage = "delivered" if delivery.delivered else "refused"
    # Only on delivery. A refused message is still waiting to be sent, and a block that said it
    # had been sent because somebody pressed the button would be the tool lying about the one
    # thing it is careful about (docs/adr/0002).
    if delivery.delivered and directive_id:
        await store.mark_directive_sent(directive_id)
    panel = await asyncio.to_thread(
        render_message, stage, session_id, text, delivery.detail, directive_id
    )
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
    form = await _form(request)
    typed = form.get("text", "").strip()
    if typed:
        rows, _ = await asyncio.to_thread(board)
        # The board is shaped before the question is aimed, and the *shaped* rows are what travels:
        # the target the human picked is a card, and only a row that has been through `shape`
        # knows which card it is under.
        projects = shape(rows, await store.groups())
        stamped = [row for p in projects for i in p.instances for row in i.rows]
        await block_runs.submit(
            store,
            typed,
            stamped,
            project=form.get("project", "").strip(),
            session=form.get("session", "").strip(),
            # The cards sitting in the output field when Send was pressed, in the order they were
            # dropped. Empty is the ordinary case and means the whole board (docs/06-console.md).
            targets=[one for one in form.get("targets", "").split(",") if one],
            thread_id=form.get("thread", "").strip(),
            # The earlier exchanges attached to this one, in the order they were attached. Empty
            # is not "everything": it means this page named nothing, and the thread is used.
            history=[one for one in form.get("history", "").split(",") if one],
        )
    if _wants_fragment(request):
        return HTMLResponse(await render_blocks())
    # Post/redirect/get: a refresh after asking must not ask again.
    return RedirectResponse("/", status_code=303)


@router.get("/blocks", response_class=HTMLResponse)
async def block_column() -> HTMLResponse:
    return HTMLResponse(await render_blocks())


@router.post("/ideas/{idea_id}/parent", response_class=HTMLResponse)
async def group_idea(idea_id: str, request: Request) -> Response:
    """Put one idea under another, or take it out of its group.

    Reached by dragging one card onto another, which is the same gesture that carries a card into
    the middle — the difference is where it lands. An empty `parent` ungroups.
    """
    parent = (await _form(request)).get("parent", "").strip()
    await store.set_idea_parent(idea_id, parent or None)
    if _wants_fragment(request):
        return HTMLResponse(await render_ideas())
    return RedirectResponse("/", status_code=303)


@router.post("/tasks", response_class=HTMLResponse)
async def queue_task(request: Request) -> Response:
    """Put approved work in a project's queue (docs/adr/0007).

    Only this route writes to that queue, and only a person reaches this route. Nothing enqueues
    itself — not the classifier, not an answer run, not a failed task, and not the loop that
    starts them.
    """
    form = await _form(request)
    key = form.get("key", "").strip()
    instruction = form.get("instruction", "").strip()
    rows, _ = await asyncio.to_thread(board)
    projects = shape(rows, await store.groups())
    named = next((project for project in projects if project.key == key), None)
    if named and instruction and named.instances:
        await store.queue_task(
            repo_key=key,
            # The checkout it runs in, resolved now: a queue that remembered a path that moved is
            # a queue that starts an agent in the wrong place.
            cwd=named.instances[0].path,
            title=form.get("title", "").strip()[:60] or instruction[:60],
            instruction=instruction,
            source_kind=form.get("source_kind", "typed").strip()[:20],
            source_ref=form.get("source_ref", "").strip() or None,
        )
    panel = await render_project(key)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/tasks/{task_id}/{action}", response_class=HTMLResponse)
async def task_action(task_id: str, action: str, request: Request) -> Response:
    """Take one out of the queue, or put a failed one back. Retry is a click (docs/adr/0007)."""
    form = await _form(request)
    key = form.get("key", "").strip()
    if action == "drop":
        await store.drop_task(task_id)
    elif action == "retry":
        task = next((t for t in await store.tasks() if t.id == task_id), None)
        if task is not None and task.failed_at is not None:
            await store.drop_task(task_id)
            await store.queue_task(
                repo_key=task.repo_key,
                cwd=task.cwd,
                title=task.title,
                instruction=task.instruction,
                source_kind=task.source_kind,
                source_ref=task.source_ref,
            )
    else:
        return PlainTextResponse("no such action", status_code=404)
    panel = await render_project(key)
    return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))


@router.post("/autostart", response_class=HTMLResponse)
async def set_autostart(request: Request) -> Response:
    """Arm or disarm one project's queue.

    Off is the default everywhere and stays that way until somebody switches it on for a named
    project. Arming clears whatever disarmed it last time, because the person doing it has just
    looked at the reason (docs/adr/0007).
    """
    form = await _form(request)
    key = form.get("key", "").strip()
    if key and form.get("armed") == "yes":
        try:
            per_hour = int(form.get("per_hour", "2"))
        except ValueError:
            per_hour = 2
        await store.arm(key, per_hour=per_hour)
    elif key:
        await store.disarm(key, why="switched off here")
    panel = await render_project(key)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/sessions/{session_id}/dispatch", response_class=HTMLResponse)
async def dispatch_here(session_id: str, request: Request) -> Response:
    """Start an agent on this text, in the project that session is in (docs/adr/0006).

    Reached from the refusal panel: nothing can be said to a session that is already running, and
    this is the thing that *can* be done with the same words instead of ending at a wall.
    """
    form = await _form(request)
    text_ = form.get("text", "").strip()
    directive_id = form.get("directive", "").strip()
    rows, _ = await asyncio.to_thread(board)
    row = next((r for r in rows if r.session.session_id == session_id), None)
    if row is None or not text_:
        panel = env.get_template("_dispatch.html").render(
            started=False, detail="that session is not on the board any more"
        )
        return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))

    result = await asyncio.to_thread(
        dispatch.start,
        dispatch.build_task(
            text_,
            project=row.session.project,
            branch=(row.tail.git_branch if row.tail else "") or "",
        ),
        cwd=row.session.cwd,
        name=text_[:40],
    )
    if result.started and directive_id:
        await store.mark_directive_dispatched(directive_id, result.agent_id)

    panel = env.get_template("_dispatch.html").render(
        started=result.started,
        detail=result.detail,
        agent_id=result.agent_id,
        project=row.session.project,
    )
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/directives/{directive_id}/dispatch", response_class=HTMLResponse)
async def dispatch_directive(directive_id: str, request: Request) -> Response:
    """The click that makes an instruction happen (docs/adr/0006).

    It starts a *new* agent in the project the instruction named, in a worktree of its own, with
    the written instruction as its prompt. It does not reach into the session that is already
    running there — there is still no client for that, and this is the half of the problem the
    CLI's background sessions do solve.
    """
    directive = await store.directive(directive_id)
    if directive is None:
        return HTMLResponse(await render_blocks(), status_code=404)
    if directive.agent_id:
        # Twice is two agents in two worktrees editing one repository.
        return HTMLResponse(await render_blocks())

    rows, _ = await asyncio.to_thread(board)
    row = next((r for r in rows if r.session.session_id == directive.session_id), None)
    if row is None:
        panel = env.get_template("_dispatch.html").render(
            started=False,
            detail="that session is not on the board any more, so its checkout is not known",
        )
        return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))

    # What the agent is told, rather than the bare line somebody typed. It starts cold in a
    # repository it has never seen, and this text is most of the difference between a useful
    # session and a wasted one (docs/adr/0006).
    block = await store.block(directive.block_id)
    task = dispatch.build_task(
        directive.text,
        project=row.session.project,
        branch=(row.tail.git_branch if row.tail else "") or "",
        notes=[block.context] if block is not None and block.context else [],
    )
    result = await asyncio.to_thread(
        dispatch.start, task, cwd=row.session.cwd, name=directive.text[:40]
    )
    if result.started:
        await store.mark_directive_dispatched(directive_id, result.agent_id)

    panel = env.get_template("_dispatch.html").render(
        started=result.started,
        detail=result.detail,
        agent_id=result.agent_id,
        project=row.session.project,
    )
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/blocks/{block_id}/delete", response_class=HTMLResponse)
async def delete_block(block_id: str, request: Request) -> Response:
    """Throw one message away, at a human's asking.

    Nothing here removes a block on its own: a question that vanished is a question you ask again
    (docs/04-threads-and-blocks.md). This is the other case — somebody looked at it and decided it
    was noise — and then it goes for real, including the run still working on it.
    """
    await block_runs.runs.stop(block_id)
    await store.delete_block(block_id)
    if _wants_fragment(request):
        return HTMLResponse(await render_blocks())
    return RedirectResponse("/", status_code=303)


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


async def _destinations() -> list[tuple[str, tracker.Destination]]:
    """Every project that has a Jira link with a variable named on it, in the order they were set.

    A link with no variable is a link and not a destination: this program refuses rather than
    reaching for an ambient credential (docs/adr/0005).
    """
    found = []
    for link in await store.links():
        destination = tracker.destination_of(link.url, link.token_env)
        if destination is not None:
            found.append((link.repo_key, destination))
    return found


@dataclass(frozen=True)
class ToFile:
    """Whether an idea can go out through the door, and what would go.

    Three human acts stand between a typed thought and an issue — keep it, draft it, file it — and
    the first two are decided here rather than hidden in a template (docs/adr/0005).
    """

    stage: str
    detail: str = ""
    idea: Idea | None = None
    body: str = ""
    destinations: list[tuple[str, tracker.Destination]] = field(default_factory=list)
    key: str = ""
    url: str = ""


async def _to_file(idea_id: str) -> ToFile:
    idea = await store.idea(idea_id)
    if idea is None:
        return ToFile("gone", detail="that idea is not in the inbox any more")

    filing = await store.filing_of(idea_id)
    if filing is not None:
        return ToFile("filed", key=filing.issue_key, url=filing.url)
    if idea.state not in ("kept", "promoted"):
        return ToFile("gone", detail="an idea is filed after it is kept, not before")

    ticket = next((d for d in await store.drafts_for(idea_id) if d.kind == "ticket"), None)
    if ticket is None:
        return ToFile("gone", detail="draft the ticket first — what is filed is what you read")

    destinations = await _destinations()
    if not destinations:
        return ToFile(
            "gone",
            detail="no project has a Jira link with an environment variable on it yet — "
            "add one with the ⋯ on a project card",
        )
    return ToFile("confirm", idea=idea, body=ticket.body, destinations=destinations)


def _panel(plan: ToFile, repo_key: str = "") -> str:
    """The panel for whichever of the four endings this is."""
    chosen = repo_key or (plan.destinations[0][0] if plan.destinations else "")
    destination = next(
        (d for key, d in plan.destinations if key == chosen),
        plan.destinations[0][1] if plan.destinations else None,
    )
    return env.get_template("_file.html").render(
        stage=plan.stage,
        detail=plan.detail,
        idea=plan.idea,
        body=plan.body,
        key=plan.key,
        url=plan.url,
        destination=destination,
        repo_key=chosen,
    )


@router.get("/ideas/{idea_id}/file", response_class=HTMLResponse)
async def review_filing(idea_id: str, request: Request, key: str = "") -> Response:
    """Step one: the ticket in full, beside where it would land. Nothing is sent by opening it."""
    panel = _panel(await _to_file(idea_id), key)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/ideas/{idea_id}/file", response_class=HTMLResponse)
async def file_idea(idea_id: str, request: Request) -> Response:
    """Step two: the click. One issue, once, and whatever came back is what is rendered.

    The checks of step one run again here rather than being trusted from it: a page can be stale,
    a second tab can have filed it, and the one thing this route must never do is create the same
    issue twice (docs/adr/0005).
    """
    form = await _form(request)
    plan = await _to_file(idea_id)
    if plan.stage != "confirm":
        panel = _panel(plan)
        return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))

    repo_key = form.get("key", "").strip() or plan.destinations[0][0]
    destination = next(
        (d for key, d in plan.destinations if key == repo_key), plan.destinations[0][1]
    )
    summary, _, description = plan.body.partition("\n")

    result = await asyncio.to_thread(
        tracker.file_issue, destination, summary.strip() or "an idea", description.strip()
    )
    if not result.filed:
        panel = _panel(ToFile("refused", detail=result.detail, body=plan.body))
        return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))

    await store.record_filing(idea_id=idea_id, tracker="jira", issue_key=result.key, url=result.url)
    panel = _panel(ToFile("filed", key=result.key, url=result.url))
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


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
    where = form.get("from")
    if _wants_fragment(request):
        if where == "card":
            return HTMLResponse(await render_blocks())
        if where == "column":
            return HTMLResponse(await render_ideas())
        return HTMLResponse(await render_inbox())
    return RedirectResponse("/" if where in ("card", "column") else "/ideas", status_code=303)


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
