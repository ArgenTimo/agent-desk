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
import csv
import io
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup, escape

from agent_desk import connectors, dispatch, peer, tracker
from agent_desk import secrets as kept
from agent_desk.config import settings
from agent_desk.ideas import appraise, bench, chart, describe, meeting
from agent_desk.observe import attach, registry, transcript
from agent_desk.observe.model import (
    AttentionHint,
    Session,
    TranscriptTail,
    attention_hint,
    lost_the_canary,
    now_ms,
    since,
    triage_rank,
)
from agent_desk.observe.shape import repository_of
from agent_desk.store.repo import (
    DRAFT_KINDS,
    Group,
    Idea,
    IdeaState,
    Kicking,
    ProjectLink,
    Store,
    Thread,
)
from agent_desk.web import autostart, blockers, plans
from agent_desk.web import blocks as block_runs
from agent_desk.web import kicking as nudge

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


def signed(row: object, name: str) -> bool:
    """Has this session stopped signing its replies with the name it was given?

    A reading, and only ever of a session this console started and told to sign — an unsigned
    reply from anybody else's session means nothing at all (023-canary.sql).
    """
    tail = getattr(row, "tail", None)
    last = getattr(tail, "last_entry", None) if tail else None
    if last is None or last.role != "assistant" or not last.text:
        return True
    return not lost_the_canary(last.text, name)


def _at(when_ms: object) -> str:
    """A wall-clock time from unix milliseconds — when a wait is over, in local time.

    Local rather than UTC because the only reader is sitting at this machine, and "back at 14:20"
    is a sentence somebody can act on where an offset is one more thing to work out.
    """
    if not isinstance(when_ms, int) or when_ms <= 0:
        return ""
    return datetime.fromtimestamp(when_ms / 1000).strftime("%H:%M")


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
    # The escape is the first line of this function and the substitutions come after it, so what
    # is wrapped here is already text. `tests/unit/test_security_surface.py` asserts that no tag
    # but these two can appear in the output, for any input.
    return Markup(out)  # nosec B704


# The registry's three words, said the way somebody who does not use a terminal would say them.
# The word itself stays on the tooltip: this renders a fact, it does not replace one.
PLAINLY = {"busy": "working", "idle": "idle", "shell": "running a command"}


def _plainly(status: str) -> str:
    return PLAINLY.get(status, status)


def _tokens(count: int | None) -> str:
    """A context size the way a person says it: 767k, 12k, 900."""
    if not count:
        return ""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M".replace(".0M", "M")
    if count >= 1_000:
        return f"{count // 1000}k"
    return str(count)


env.filters["tokens"] = _tokens
env.filters["plainly"] = _plainly
env.filters["prose"] = _prose
env.filters["ago"] = _ago
env.filters["clock"] = _clock
env.filters["at"] = _at


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


async def board_work() -> dict[str, dict[str, int]]:
    """How much work is waiting, running, finished and stuck — per project *and* per session.

    "Показывать к-во закрытых и заблокированных задач у каждого проекта/инстанса/сессии/агента в
    карточке, чтобы можно было оценить что и сколько сделано." A project's total answers "is
    anything happening here"; the per-session count answers "who has actually done anything",
    which is the question somebody looking at four sessions is really asking.

    Keyed by repository for a project and by the agent's short id for a session, so one table
    serves both and a card looks itself up by the name it already has.

    Counted from the queue rather than from a tracker: this is what the console started and can
    account for. A number taken from somewhere it cannot see would be a number nobody can check
    (docs/adr/0005, which refuses to read a tracker back).
    """
    counted: dict[str, dict[str, int]] = {}

    def tally_for(key: str) -> dict[str, int]:
        return counted.setdefault(key, {"waiting": 0, "running": 0, "done": 0, "stuck": 0})

    for task in await store.tasks(limit=500):
        # Everything a task counts towards: its project always, and the agent that ran it when
        # one did. A task nobody started belongs to the project alone.
        keys = [task.repo_key] + ([task.agent_id] if task.agent_id else [])
        for key in keys:
            tally = tally_for(key)
            if task.failed_at:
                tally["stuck"] += 1
            elif task.waiting:
                tally["waiting"] += 1
            elif task.finished_at:
                tally["done"] += 1
            else:
                tally["running"] += 1

    # And what somebody else's board says is stuck, against the project it is on.
    for stuck in await store.tracker_blockers():
        tally_for(stuck.repo_key)["stuck"] += 1
    return counted


async def board_rows_and_kicks() -> tuple[list[BoardRow], dict[str, Kicking]]:
    """What the plans strip needs, read once. A convenience for the stream, which has no board row
    of its own to hand over."""
    rows, _ = await asyncio.to_thread(board)
    return rows, await board_kicks()


async def board_plans(rows: list[BoardRow], kicks: dict[str, Kicking]) -> str:
    """The subscriptions strip above the projects (agent_desk/web/plans.py)."""
    return env.get_template("_plans.html").render(
        plans=plans.plans(
            await store.subscriptions(),
            rows,
            await store.session_subscriptions(),
            kicks,
            now_ms(),
        )
    )


async def board_canaries() -> dict[str, str]:
    """The signature each session this console started was told to keep (023-canary.sql)."""
    return await store.canaries()


async def board_kicks() -> dict[str, Kicking]:
    """Which sessions are switched on to keep going, by short id (docs/adr/0009).

    Read with the board for the same reason the links are: it is a handful of rows, and a button
    whose state arrives one round trip after the card is a button that looks broken.
    """
    return {arming.short_id: arming for arming in await store.kicked_sessions()}


async def board_links() -> dict[str, list[ProjectLink]]:
    """Every project's links, keyed by repository, for the menu on its card."""
    grouped: dict[str, list[ProjectLink]] = {}
    for link in await store.links():
        grouped.setdefault(link.repo_key, []).append(link)
    return grouped


def render_board(
    groups: list[Group] | None = None,
    links: dict[str, list[ProjectLink]] | None = None,
    work: dict[str, dict[str, int]] | None = None,
    kicks: dict[str, Kicking] | None = None,
    canaries: dict[str, str] | None = None,
    plans_html: str = "",
) -> str:
    """The fragment the page holds and every server-sent event replaces."""
    rows, notices = board()
    projects = shape(rows, groups or [])
    return env.get_template("_board.html").render(
        rows=rows,
        projects=projects,
        notices=notices,
        # What each project is linked to, for the menu on its card. Read with the board rather
        # than fetched when the menu opens: it is four links, and a click that waits for a round
        # trip is a click that feels broken.
        links=links or {},
        # What it has going on and what it has got through — from this program's own queue, which
        # is the only work it can honestly count (docs/adr/0007).
        work=work or {},
        # Which sessions are switched on not to idle, so the button on each card shows its own
        # state rather than the same state on all of them (docs/adr/0009).
        kicks=kicks or {},
        # The signature each session this console started was told to keep, so the card can say
        # when one stops (023-canary.sql).
        canaries=canaries or {},
        # The plans strip above the projects, rendered separately because it is about sessions
        # across projects rather than about any one of them (agent_desk/web/plans.py).
        plans=plans_html,
        # A reading of the text, in one place rather than in the template.
        signed=signed,
        flagged=sum(1 for row in rows if row.hint.waiting),
    )


def _about(kind: str, rows: list[BoardRow]) -> str:
    """What a card is described from — the facts, as lines, for `ideas/describe.py`.

    Deliberately the same text the description is cached against: if this changes, the sentence is
    written again, and if it does not, the cached one stands.
    """
    said: list[str] = []
    for row in rows[:3]:
        tail = row.tail
        said += [
            f"name: {row.session.name}",
            f"project: {row.session.project}",
            f"status: {row.session.status}",
        ]
        if tail and tail.title:
            said.append(f"working on: {tail.title}")
        if tail and tail.git_branch:
            said.append(f"branch: {tail.git_branch}")
        if tail and tail.last_entry and tail.last_entry.text:
            said.append(f"last said: {tail.last_entry.text[:200]}")
    return "\n".join(said)


async def describe_card(kind: str, card_id: str) -> str:
    """One sentence about this card, written once and kept (028-card-descriptions.sql)."""
    if kind == "idea":
        idea = await store.idea(card_id)
        if idea is None:
            return ""
        return await describe.describe(
            store, f"idea:{card_id}", "idea somebody wrote down", idea.text[:600]
        )
    rows, _ = await asyncio.to_thread(board)
    projects = shape(rows, await store.groups())
    stamped = [row for project in projects for one in project.instances for row in one.rows]
    if kind in ("session", "agent"):
        mine = [row for row in stamped if row.session.session_id == card_id]
    elif kind == "instance":
        mine = [row for row in stamped if row.session.cwd == card_id]
    elif kind == "project":
        mine = [row for row in stamped if row.project_key == card_id]
    else:
        return ""
    if not mine:
        return ""
    return await describe.describe(store, f"{kind}:{card_id}", kind, _about(kind, mine))


def render_card(kind: str, card_id: str, groups: list[Group] | None = None, said: str = "") -> str:
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
    return env.get_template("_card.html").render(kind=kind, rows=chosen, card_id=card_id, said=said)


def render_tail(session_id: str) -> str:
    """The drill-down: the tail of one transcript, and nothing else (docs/06-console.md)."""
    tail = transcript.read_tail(session_id)
    return env.get_template("_tail.html").render(tail=tail)


async def render_blocks() -> str:
    """Every recent block, for the workbench to place the open chat's on the surface.

    The bound is generous rather than tight because the page filters by chat afterwards: with the
    old fifty, a console with several chats open rendered fifty blocks that could all belong to
    *other* chats, and the chat you were looking at came out empty. That is a surface that says
    "nothing here" about a conversation you can see in the tab bar.
    """
    rows = await store.blocks(limit=250)
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
    every = await store.ideas()
    ideas: dict[str, list[Idea]] = {}
    for idea in reversed(every):
        if idea.block_id:
            ideas.setdefault(idea.block_id, []).append(idea)

    # Which written-down thoughts a request turned out to be about — a guess by a short run,
    # rendered as an offer with a button rather than as a fact (docs/05-ideas.md).
    by_id = {idea.id: idea for idea in every}
    about = {
        block_id: [by_id[one] for one in idea_ids if one in by_id]
        for block_id, idea_ids in (await store.ideas_of_blocks()).items()
    }
    directives = {d.block_id: d for d in await store.directives()}
    return env.get_template("_blocks.html").render(
        blocks=rows,
        drafted=await store.drafted("ticket"),
        filings={filing.idea_id: filing for filing in await store.filings()},
        open_threads=open_threads + missing,
        threads_by_id={thread.id: thread for thread in open_threads + missing},
        ideas=ideas,
        about=about,
        # Which of them an agent has in its hands right now, so the console can say so wherever an
        # idea appears rather than only where the work was started.
        working=await store.ideas_in_flight(),
        # Work that was written down and is waiting for a seat: a request is not done until it is
        # done, and a console that said nothing about it would be pretending otherwise.
        waiting={
            task.block_id: task for task in await store.tasks() if task.waiting and task.block_id
        },
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


# How the ideas column may be ordered, and the word each one shows. Newest first is the default
# because a notebook is read from the end; the others exist because a list of sixty is not read
# from the end at all, it is searched.
IDEA_SORTS: tuple[tuple[str, str], ...] = (
    ("newest", "newest first"),
    ("oldest", "oldest first"),
    ("project", "by project"),
    ("state", "by what has happened to it"),
    ("needs", "by what it needs next"),
)
IDEA_SORT_KEY = "ideas.sort"
# Which project the right-hand column is narrowed to, or empty for all of them. In the store for
# the same reason the sort is: a server-sent event replaces those columns every couple of seconds,
# and a filter that resets two seconds after it is set is a filter that looks broken.
FOCUS_KEY = "board.project"
# Whether the right-hand column shows the pool or the tickets read from the projects' own boards.
# One column, two things it can be about: an idea is a thought somebody had here, and a ticket is
# work somebody decided elsewhere (docs/adr/0010). Showing them mixed would make the pool look
# like a backlog, which is the failure docs/adr/0005 is built around.
COLUMN_KEY = "column.shows"

# Where an idea with no project sorts: last, and named rather than blank — "no project" is a fact
# about it, and a group of them at the top would push the answered ones down.
_NO_PROJECT = "\uffff"
# The order states are read in: what is still a question first, what is settled last.
_STATE_ORDER = {"new": 0, "kept": 1, "promoted": 2, "done": 3, "dropped": 4}
# What a background pass made of an idea, in the order somebody would work through them: the ones
# that need a decision first, because nothing else can start until those are made. Unread last —
# an idea nobody has looked at is not a judgement about it (agent_desk/ideas/appraise.py).
_SHAPE_ORDER = {"decide": 0, "ready": 1, "built": 2}


def _sorted_roots(roots: list[Idea], how: str) -> list[Idea]:
    """The top-level ideas in the order somebody asked for. Newest first when nobody has.

    Every order is a *stable* re-sort of newest-first, so two ideas in the same project or the
    same state still read newest first inside their group — which is the order a notebook has.
    """
    if how == "oldest":
        return list(reversed(roots))
    if how == "project":
        return sorted(roots, key=lambda idea: idea.project_key or _NO_PROJECT)
    if how == "state":
        return sorted(roots, key=lambda idea: _STATE_ORDER.get(idea.state, 9))
    if how == "needs":
        return sorted(roots, key=lambda idea: _SHAPE_ORDER.get(idea.shape or "", 9))
    return roots


async def render_blockers() -> str:
    """The top of the right column: what has stopped (agent_desk/web/blockers.py)."""
    only = await store.setting(FOCUS_KEY)
    return env.get_template("_blockers.html").render(
        found=await blockers.blockers(store, only), only=only
    )


async def render_ideas() -> str:
    """The bottom half of the right column: what has been written down.

    Dropped ideas are not shown here. The inbox keeps them — an idea's history is part of what the
    notebook is for — but a column somebody glances at is about what is still live.
    """
    how = await store.setting(IDEA_SORT_KEY, "newest")
    only = await store.setting(FOCUS_KEY)
    ideas = [idea for idea in await store.ideas() if idea.state not in ("dropped", "done")]
    if only:
        # A thought with no project is about whatever is in front of you, so it survives the
        # narrowing — the same rule the blockers follow, for the same reason.
        ideas = [idea for idea in ideas if (idea.project_key or "") in ("", only)]
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
        working=await store.ideas_in_flight(),
        roots=_sorted_roots(list(reversed(roots)), how),
        children=children,
        sorts=IDEA_SORTS,
        sorted_by=how,
        # The words the pass's two answers are shown as, in one place rather than in the template.
        says=appraise.SAYS,
        # Which project the column is narrowed to, so it can say so rather than looking empty.
        only=only,
        only_named=await _project_name(only),
        # What depends on what (024-idea-links.sql). Read with the column: it is a handful of
        # rows, and a card that fetched its own links would be a card that flickers.
        links=await store.idea_links(),
        # Their summaries, so a link can name the idea at the other end of it.
        named={idea.id: idea.summary for idea in ideas},
        counted=len(ideas),
        # A root with nothing under it is an idea, not a group of one.
        grouped=len([idea for idea in ideas if children.get(idea.id)]),
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
        # Where an idea went, if it went anywhere. The inbox is the place that keeps the history,
        # so it is the place that has to show the issue key (docs/05-ideas.md).
        filings={filing.idea_id: filing for filing in await store.filings()},
        working=await store.ideas_in_flight(),
        drafting={idea_id for idea_id, _ in block_runs.DRAFTING},
    )


@router.get("/", response_class=HTMLResponse)
async def page() -> HTMLResponse:
    return HTMLResponse(await render_page())


@router.get("/board.csv", response_class=PlainTextResponse)
async def board_csv() -> Response:
    """The board as a file, for the questions a board cannot answer.

    "How much of last week was llm-developer-2" is a spreadsheet question, and a console that
    refuses to hand over its rows makes somebody screenshot them. One row a session, the same
    facts the cards show and nothing inferred: the flag is a guess and guesses do not belong in a
    column somebody will sum (docs/03-session-observation.md).
    """
    rows, _ = await asyncio.to_thread(board)
    projects = shape(rows, await store.groups())
    out = io.StringIO()
    sheet = csv.writer(out)
    sheet.writerow(
        [
            "project",
            "checkout",
            "session",
            "name",
            "status",
            "kind",
            "branch",
            "context_tokens",
            "updated_at",
            "title",
            "last_entry",
        ]
    )
    for project in projects:
        for instance in project.instances:
            for row in instance.rows:
                tail = row.tail
                last = tail.last_entry if tail else None
                sheet.writerow(
                    [
                        project.name,
                        instance.path,
                        row.session.session_id,
                        row.session.name,
                        row.session.status,
                        row.session.kind,
                        (tail.git_branch if tail else "") or "",
                        (tail.context_tokens if tail else "") or "",
                        row.session.updated_at,
                        (tail.title if tail else "") or "",
                        (last.text if last else "") or "",
                    ]
                )
    return PlainTextResponse(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="board.csv"'},
    )


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
        ideas=await render_column(),
        blockers=await render_blockers(),
        board=env.get_template("_board.html").render(
            rows=rows,
            projects=projects,
            notices=notices,
            links=await board_links(),
            work=await board_work(),
            kicks=await board_kicks(),
            canaries=await board_canaries(),
            plans=await board_plans(rows, await board_kicks()),
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


@router.post("/blockers/cleared", response_class=HTMLResponse)
async def say_cleared(request: Request) -> Response:
    """Somebody says a blocker is cleared. It stays, and waits to be checked.

    "Человек может нажать кнопку «разблокировано» — блокер остаётся, но переходит в статус
    уточнения; агенты проверяют, и только если разблокировано — блок уходит."

    The button not clearing anything is the whole design. A blocker that vanished because a button
    was pressed is one that comes back as a surprise two hours later, when the agent that was
    waiting on it fails for exactly the same reason.
    """
    form = await _form(request)
    name = form.get("name", "").strip()
    if name:
        if form.get("undo") == "yes":
            await store.forget_claim(name)
        else:
            await store.claim_cleared(name, form.get("said", "").strip())
    panel = await render_blockers()
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(""))


@router.get("/cards/{kind}/full", response_class=HTMLResponse)
async def card_in_full(kind: str, id: str = "") -> HTMLResponse:
    """Everything about one card: the console, how long it has been up, what it is carrying.

    A route of its own, and fetched only when somebody presses for it — "фул-дата открывается
    только если пользователь намеренно нажмёт на кнопку". A transcript tail is tens of kilobytes
    and a board of twenty cards must not carry twenty of them by default.
    """
    if kind not in ("session", "agent"):
        return HTMLResponse("", status_code=404)
    rows, _ = await asyncio.to_thread(board)
    row = next((one for one in rows if one.session.session_id == id), None)
    if row is None:
        return HTMLResponse("", status_code=404)
    return HTMLResponse(
        env.get_template("_card_full.html").render(
            row=row,
            tail=await asyncio.to_thread(transcript.read_tail, id),
            started=row.session.updated_at,
        )
    )


@router.get("/cards/{kind}", response_class=HTMLResponse)
async def card(kind: str, id: str = "") -> HTMLResponse:
    """What one card contains. The id is a query parameter because two of the kinds are identified
    by a filesystem path, and a path does not fit in a path segment."""
    if kind == "idea":
        # An idea is not a session and has no board row: what it contains is what was written.
        idea = await store.idea(id)
        return HTMLResponse(
            env.get_template("_card_idea.html").render(
                idea=idea, said=await describe_card("idea", id) if idea else ""
            ),
            status_code=200 if idea else 404,
        )
    if kind == "connector":
        # A connector dragged onto the bench: what it is, what this console can do with it, and
        # the address — so a question asked with it there is asked with that in front of both of
        # you (agent_desk/connectors.py).
        repo_key, _, name = id.partition("::")
        link = next((one for one in await store.links(repo_key) if one.name == name), None)
        return HTMLResponse(
            env.get_template("_card_connector.html").render(
                link=link,
                kind=connectors.kind_of(
                    (link.kind or connectors.guess(link.url, link.name)) if link else "other"
                ),
                project=await _project_name(repo_key),
            ),
            status_code=200 if link else 404,
        )
    if kind == "blocker":
        # Recomputed rather than stored: a blocker is a view of facts that live elsewhere, and
        # "it is gone" is the ordinary outcome — it means the thing got unstuck.
        stuck = await blockers.one(store, id)
        return HTMLResponse(
            env.get_template("_card_blocker.html").render(one=stuck, card_id=id),
            status_code=200 if stuck else 404,
        )
    groups = await store.groups()
    said = await describe_card(kind, id)
    markup = await asyncio.to_thread(render_card, kind, id, groups, said)
    return HTMLResponse(markup, status_code=200 if markup else 404)


async def _kept_the_variable(key: str, name: str, typed: str) -> bool:
    return any(link.name == name and link.token_env == typed for link in await store.links(key))


async def render_project(key: str, refused: str = "") -> str:
    """The settings panel for one project, rendered where the write path's panel goes."""
    rows, _ = await asyncio.to_thread(board)
    projects = shape(rows, await store.groups())
    named = next((project for project in projects if project.key == key), None)
    return env.get_template("_project.html").render(
        refused=refused,
        key=key,
        name=named.name if named else key,
        links=await store.links(key),
        # What each connector is, and therefore what this console can do with it. The functions
        # rather than the answers, because the template asks one per row (agent_desk/connectors.py).
        kinds=connectors.KINDS,
        kind_of=connectors.kind_of,
        guess=connectors.guess,
        tasks=await store.tasks(repo_key=key),
        env_names=await store.env(key),
        arming=await store.autostart(key),
        # The console says exactly what the loop decided, because it asks the same function.
        why_not=await autostart.why_not(store, key),
        explore_why=await autostart.why_not_explore(store, key),
        # What is simply true here, whatever the task is. It goes verbatim into every agent this
        # console starts in this project (020-project-note.sql).
        note=await store.project_note(key),
        # The words they use here, and the ones that mean the same everywhere (021-glossary.sql).
        terms=await store.terms(key),
    )


@router.get("/projects/page", response_class=HTMLResponse)
async def project_page(key: str = "") -> HTMLResponse:
    """A project's own page: what it is linked to, what it needs in the environment, its queue.

    A page rather than the panel in the middle, because the middle is where the work happens and
    settings are not work — the `⋯` on a card offers both, and this is the one you leave open on a
    second screen while you fix something.
    """
    return HTMLResponse(
        env.get_template("project.html").render(
            # HTML this program just rendered from its own template with autoescape on, being
            # placed inside another of its own templates.
            panel=Markup(await render_project(key)),  # nosec B704
            key=key,
        )
    )


@router.get("/projects/instance", response_class=HTMLResponse)
async def new_instance_form(request: Request, key: str = "") -> Response:
    """The form behind "New instance…": a name, a specialisation, and what it will do."""
    rows, _ = await asyncio.to_thread(board)
    projects = shape(rows, await store.groups())
    named = next((project for project in projects if project.key == key), None)
    panel = env.get_template("_instance.html").render(
        stage="ask",
        key=key,
        name=named.name if named else key,
        # Filled in rather than empty: naming a thing is a decision, and a decision on a form is
        # a pause. Anybody may type over it (dispatch.a_name).
        suggested=dispatch.a_name(),
        cwd=named.instances[0].path if named and named.instances else "",
        env_names=await store.env(key),
    )
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/projects/instance", response_class=HTMLResponse)
async def new_instance(request: Request) -> Response:
    """Make a copy of the checkout with an agent working in it (docs/adr/0006).

    A worktree of the same repository rather than a clone: the two are linked by the repository
    itself, which is what the person asking for this described, and it costs no second fetch of
    anything. The agent is started with an introduction rather than a task — it is a new pair of
    hands in a project, and the first thing it should do is read.
    """
    form = await _form(request)
    key = form.get("key", "").strip()
    who = form.get("name", "").strip()[:40] or dispatch.a_name()
    doing = form.get("doing", "").strip()[:200]

    rows, _ = await asyncio.to_thread(board)
    projects = shape(rows, await store.groups())
    named = next((project for project in projects if project.key == key), None)
    if named is None or not named.instances:
        panel = env.get_template("_instance.html").render(
            stage="failed", detail="that project has no checkout on this machine", key=key
        )
        return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))

    cwd = named.instances[0].path
    needed = [one.name for one in await store.env(key)]
    result = await asyncio.to_thread(
        dispatch.start,
        dispatch.introduce(who, project=named.name, doing=doing, env_names=needed),
        cwd=cwd,
        name=who,
    )
    if result.started:
        # It was told to sign its replies with this name, so the board can notice when it stops
        # (023-canary.sql). Only sessions this console started have one.
        await store.keep_canary(result.agent_id, who)
    panel = env.get_template("_instance.html").render(
        stage="started" if result.started else "failed",
        detail=result.detail,
        agent_id=result.agent_id,
        who=who,
        key=key,
        name=named.name,
    )
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/project-env", response_class=HTMLResponse)
async def set_project_env(request: Request) -> Response:
    """Name a variable this project's agents need. The name; never the value."""
    form = await _form(request)
    key = form.get("key", "").strip()
    name = form.get("name", "").strip()[:64]
    if key and name and form.get("remove"):
        await store.remove_env(key, name)
    elif key and name:
        await store.set_env(repo_key=key, name=name, note=form.get("note", "").strip()[:120])
    panel = await render_project(key)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


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
    variable = form.get("token_env", "").strip()[:64]
    if key and name and url.startswith(("http://", "https://")):
        # What kind of connector it is decides what this console can do with it. Chosen where
        # somebody chose, and worked out from the address where they left it to us — a guess that
        # saves a decision rather than making one (agent_desk/connectors.py).
        chosen = form.get("kind", "").strip()
        kind = chosen if chosen in connectors.BY_NAME else connectors.guess(url, name)
        await store.set_link(repo_key=key, name=name, url=url, token_env=variable, kind=kind)

    # The token itself, if one was typed. It goes to this machine's own secret file under the name
    # on the link — never to the store, which a second application serves a view out of, and never
    # back to a screen: the panel can only ever say whether there is one (agent_desk/secrets.py).
    secret = form.get("token", "")
    said = ""
    if secret and not variable:
        said = "name the token first — a secret needs somewhere to be looked up from."
    elif secret:
        kept.keep(variable, secret.strip())
        said = f"{variable} is set on this machine. It is not stored with the project."
    elif variable and not await _kept_the_variable(key, name, variable):
        said = (
            "that is not a name — nothing was stored. A name looks like JIRA_TOKEN; the token "
            "itself goes in the field beside it."
        )
    if said:
        return HTMLResponse(await render_project(key, refused=said))
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
            return HTMLResponse(
                await asyncio.to_thread(
                    render_board,
                    await store.groups(),
                    await board_links(),
                    await board_work(),
                    await board_kicks(),
                    await board_canaries(),
                    await board_plans(*await board_rows_and_kicks()),
                )
            )
    return RedirectResponse("/", status_code=303)


@router.post("/projects/{group_id}/members", response_class=HTMLResponse)
async def add_to_project(group_id: str, request: Request) -> Response:
    """What a card dropped onto a project card does."""
    repo_key = (await _form(request)).get("repo_key", "").strip()
    if repo_key:
        await store.add_to_group(group_id, repo_key)
    if _wants_fragment(request):
        return HTMLResponse(
            await asyncio.to_thread(
                render_board,
                await store.groups(),
                await board_links(),
                await board_work(),
                await board_kicks(),
            )
        )
    return RedirectResponse("/", status_code=303)


@router.post("/projects/{group_id}/dissolve", response_class=HTMLResponse)
async def dissolve_project(group_id: str, request: Request) -> Response:
    """Ungrouping returns every repository in it to being its own project. Nothing is lost."""
    await store.delete_group(group_id)
    if _wants_fragment(request):
        return HTMLResponse(
            await asyncio.to_thread(
                render_board,
                await store.groups(),
                await board_links(),
                await board_work(),
                await board_kicks(),
            )
        )
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
            # Blocks somebody wrote on the bench themselves: text, not a card to look up.
            notes_=form.get("notes", ""),
        )
    if _wants_fragment(request):
        return HTMLResponse(await render_blocks())
    # Post/redirect/get: a refresh after asking must not ask again.
    return RedirectResponse("/", status_code=303)


@router.get("/blocks", response_class=HTMLResponse)
async def block_column() -> HTMLResponse:
    return HTMLResponse(await render_blocks())


@router.get("/workbench/ties", response_class=HTMLResponse)
async def workbench_ties(cards: str = "") -> HTMLResponse:
    """Which cards on the workbench are related, and how — as data, not as a picture.

    The diagram this replaces drew its own boxes, which meant the cards you had put on the bench
    were shown twice: once as themselves and once as two truncated words in a rectangle. What
    somebody asked for is the cards *they can read*, with the relations drawn between them — so
    this returns the pairs and the page draws the lines behind the real cards.
    """
    picked = [one for one in cards.split(",") if one]
    rows, _ = await asyncio.to_thread(board)
    projects = shape(rows, await store.groups())
    stamped = [row for project in projects for one in project.instances for row in one.rows]
    drawn = bench.lay_out(picked, stamped, await store.ideas(limit=400), await store.idea_links())
    ties = [{"from": tie.from_id, "to": tie.to_id, "says": tie.says} for tie in drawn.ties]
    return HTMLResponse(json.dumps(ties), media_type="application/json")


@router.get("/workbench", response_class=HTMLResponse)
async def workbench_diagram(cards: str = "") -> HTMLResponse:
    """The cards on the workbench as a diagram, with the relations between them drawn.

    "Отображение на верстаке не как просто блоки, а как диаграммы со всеми взаимосвязями." A stack
    of cards says what each one is; it cannot say that this session is in that project, or that
    this idea needs that one. The relation is the thing a diagram has room for and a stack does
    not.

    Only relations this console already knows are drawn, and only between cards that are actually
    on the bench: a line to something you cannot see is a line that explains nothing.
    """
    picked = [one for one in cards.split(",") if one]
    rows, _ = await asyncio.to_thread(board)
    # The *shaped* rows: `project_key` is stamped by `shape`, and without it a session and the
    # project it runs in are two boxes with nothing between them.
    projects = shape(rows, await store.groups())
    stamped = [row for project in projects for one in project.instances for row in one.rows]
    return HTMLResponse(
        env.get_template("_workbench.html").render(
            drawn=bench.lay_out(
                picked,
                stamped,
                await store.ideas(limit=400),
                await store.idea_links(),
            ),
            width=chart.BOX_WIDTH,
            height=chart.BOX_HEIGHT,
        )
    )


@router.post("/ideas/meeting", response_class=HTMLResponse)
async def read_meeting(request: Request) -> Response:
    """Paste what was said in a meeting; get the ideas in it (docs/10-meeting-intake.md §1+).

    It proposes and does not decide. Everything it finds arrives in the pool as an ordinary idea
    in the `new` state, marked as having come from a meeting, and a person keeps or discards each
    one exactly as they would a thought they typed — because a transcript is full of things that
    were said and not meant.
    """
    form = await _form(request)
    said = form.get("transcript", "").strip()
    if not said:
        return HTMLResponse(await render_ideas())
    # A run rather than a wait: a transcript is read in passes and each one is a model call, and
    # the field must come back immediately the way every other capture does.
    where = form.get("key", "").strip() or None

    async def read() -> None:
        await meeting.read_meeting(store, said, project_key=where)

    if block_runs.runs.running:
        block_runs.runs.start(f"meeting:{now_ms()}", read)
    else:
        # No group to run it in, which is not a state the console is ever in — but a route that
        # raises rather than answers is a 500 where a page belongs, and this is the second call
        # site to need the same guard the drafts use.
        log.warning("a meeting was pasted with no task group to read it in")
    panel = await render_ideas()
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(""))


@router.get("/ideas/map", response_class=HTMLResponse)
async def idea_map() -> HTMLResponse:
    """The pool as a picture (agent_desk/ideas/chart.py).

    A page of its own rather than a column: it is the whole pool at once, which is the opposite of
    what the column is for. Everything that is not discarded is on it, including what is built —
    half the shape of a pool is what is already there.
    """
    ideas = [idea for idea in await store.ideas(limit=400) if idea.state != "dropped"]
    return HTMLResponse(
        env.get_template("map.html").render(
            chart=chart.lay_out(ideas, await store.idea_links()),
            width=chart.BOX_WIDTH,
            height=chart.BOX_HEIGHT,
        )
    )


@router.post("/ideas/link", response_class=HTMLResponse)
async def link_ideas(request: Request) -> Response:
    """Say that one idea needs another, or that the two of them together make a third thing.

    Grouping already says "this is part of that" (`parent_id`). These two say what it cannot: a
    dependency between whole ideas, and a pair whose combination is worth more than either
    (024-idea-links.sql).
    """
    form = await _form(request)
    drop = form.get("drop", "").strip()
    if drop:
        await store.unlink_ideas(drop)
    else:
        kind = form.get("kind", "needs").strip()
        await store.link_ideas(
            from_id=form.get("from_id", "").strip(),
            to_id=form.get("to_id", "").strip(),
            kind="touches" if kind == "touches" else "needs",
        )
    panel = await render_ideas()
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(""))


async def _project_name(key: str) -> str:
    """A project's own name for a key, or the key when there is nothing better."""
    if not key:
        return ""
    rows, _ = await asyncio.to_thread(board)
    named = next((one for one in shape(rows, await store.groups()) if one.key == key), None)
    return named.name if named else key.split(":")[-1]


async def render_tickets() -> str:
    """The right-hand column showing the tickets read from the projects' own boards.

    Read from the queue rather than from the tracker: the loop already pulled them and marked them
    `tracker`, and a column that made its own network call every two seconds would be a column
    that hangs when somebody's Jira is slow (docs/adr/0010).
    """
    only = await store.setting(FOCUS_KEY)
    tasks = [
        task
        for task in await store.tasks(limit=200)
        if task.source_kind == "tracker" and (not only or task.repo_key == only)
    ]
    return env.get_template("_tickets.html").render(
        tasks=tasks,
        only=only,
        only_named=await _project_name(only),
        stuck=[one for one in await store.tracker_blockers() if not only or one.repo_key == only],
    )


async def render_column() -> str:
    """Whichever of the two the right-hand column is set to show."""
    if await store.setting(COLUMN_KEY) == "tickets":
        return await render_tickets()
    return await render_ideas()


@router.post("/column", response_class=HTMLResponse)
async def set_column(request: Request) -> Response:
    """Switch the right-hand column between the pool and the board.

    "В столбце с идеями/блокерами можно переключить режим на jira таски." Two things one column
    can be about, and they are kept apart rather than merged: an idea is a thought somebody had
    here and a ticket is work somebody decided elsewhere, and a list holding both would make the
    pool read as a backlog — which is the failure docs/adr/0005 is built around.
    """
    form = await _form(request)
    shows = form.get("shows", "ideas").strip()
    await store.set_setting(COLUMN_KEY, "tickets" if shows == "tickets" else "ideas")
    panel = await render_column()
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(""))


@router.post("/projects/attach", response_class=HTMLResponse)
async def attach_project(request: Request) -> Response:
    """Add a project by pointing at it: a folder on this machine, or a repository URL.

    Running `claude` in a directory still needs no form at all, and that stays the answer in the
    README. This is for the moment somebody thinks of a project while they have its address in
    their hand and does not want to go and start a session first.

    Nothing is cloned and nothing is created. This program records where a repository lives; it
    does not fetch it (CLAUDE.md, rule two). A URL with no checkout here becomes a project with a
    link and no instance, which is exactly what it is.
    """
    form = await _form(request)
    pointed = attach.read(form.get("where", ""))
    if not pointed.ok:
        panel = env.get_template("_dispatch.html").render(started=False, detail=pointed.detail)
        return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))

    group = await store.create_group(pointed.name)
    await store.add_to_group(group.id, pointed.repo_key)
    if pointed.url:
        await store.set_link(repo_key=pointed.repo_key, name="repository", url=pointed.url)
    if pointed.path:
        # Where it is, so the queue and an exploration have a directory to work in without
        # waiting for a session to appear there first (docs/adr/0008).
        arming = await store.autostart(pointed.repo_key)
        await store.explore(
            pointed.repo_key, per_day=arming.per_day, on=arming.exploring, cwd=pointed.path
        )
    log.info("project attached", project=pointed.name, key=pointed.repo_key)

    panel = await render_project(pointed.repo_key)
    return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))


@router.post("/projects/focus", response_class=HTMLResponse)
async def focus_project(request: Request) -> Response:
    """Narrow the blockers and the ideas to one project, or open them up again.

    "Выбор проекта слева фильтрует блокеры и идеи; без выбора — всё." A board with six projects on
    it has a right-hand column about all six, and when you are working on one of them that column
    is mostly noise.

    Anything belonging to no project survives the narrowing: a thought typed with nothing on the
    workbench is about whatever is in front of you, and a failed question belongs to no repository
    at all. Hiding those behind a filter they were never part of would lose them.
    """
    form = await _form(request)
    await store.set_setting(FOCUS_KEY, form.get("key", "").strip())
    if _wants_fragment(request):
        # Both columns move together, because they are one decision.
        return HTMLResponse(await render_column())
    return HTMLResponse(await render_page(""))


@router.post("/ideas/sort", response_class=HTMLResponse)
async def sort_ideas(request: Request) -> Response:
    """How the ideas column is ordered. Kept in the store rather than in the URL.

    The column is replaced by a server-sent event every couple of seconds, and a choice held in a
    query parameter would last exactly until the next one — which is the shape of a control that
    looks broken rather than one that is off.
    """
    form = await _form(request)
    how = form.get("how", "newest").strip()
    if how in {name for name, _ in IDEA_SORTS}:
        await store.set_setting(IDEA_SORT_KEY, how)
    panel = await render_ideas()
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(""))


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
    """Start one now, take one out of the queue, or put a failed one back (docs/adr/0007)."""
    form = await _form(request)
    key = form.get("key", "").strip()
    if action == "start":
        waiting = next((t for t in await store.tasks() if t.id == task_id and t.waiting), None)
        if waiting is not None:
            claimed = await store.take_next_task(waiting.repo_key)
            if claimed is not None and claimed.id == task_id:
                result = await asyncio.to_thread(
                    dispatch.start,
                    dispatch.build_task(
                        claimed.instruction,
                        project=claimed.title,
                        **await autostart.about(store, claimed.repo_key),  # type: ignore[arg-type]
                    ),
                    cwd=claimed.cwd,
                    name=claimed.title,
                )
                if result.started:
                    await store.task_started(claimed.id, result.agent_id)
                else:
                    await store.task_failed(claimed.id, result.detail)
    elif action == "drop":
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


@router.post("/agents/{agent_id}/stop", response_class=HTMLResponse)
async def stop_agent(agent_id: str, request: Request) -> Response:
    """Stop an agent this console started (docs/adr/0006).

    The one control that matters once something is running. Its conversation is kept — `claude
    attach` opens it again — and the task it was on is marked finished, which frees the seat.
    """
    result = await asyncio.to_thread(dispatch.stop, agent_id)
    for task in await store.tasks():
        if task.agent_id == agent_id and task.finished_at is None:
            await store.finish_task(task.id)
    panel = env.get_template("_dispatch.html").render(
        started=False,
        detail=(
            f"{agent_id} was stopped. Its conversation is kept — `claude attach {agent_id}` "
            "opens it again."
            if result.started
            else f"{agent_id} would not stop: {result.detail}"
        ),
    )
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/blocks/{block_id}/implement", response_class=HTMLResponse)
async def implement_ideas(block_id: str, request: Request) -> Response:
    """Start an agent on the ideas this request turned out to be about (docs/adr/0006).

    What it is told is the request and the thoughts themselves, verbatim: the summaries are for
    scanning, and what somebody actually wrote is what the work should be built from. The ideas are
    not marked built here — that happens when the agent is gone, in one place
    (agent_desk/web/autostart.py).
    """
    block = await store.block(block_id)
    known = {idea.id: idea for idea in await store.ideas()}
    wanted = [
        known[one]
        for one in (await store.ideas_of_blocks()).get(block_id, [])
        if one in known and known[one].state != "done"
    ]
    rows, _ = await asyncio.to_thread(board)
    projects = shape(rows, await store.groups())
    # Where the work happens: the project the instruction was aimed at, or the only one there is.
    directive = next((d for d in await store.directives() if d.block_id == block_id), None)
    row = next(
        (r for r in rows if directive and r.session.session_id == directive.session_id), None
    )
    named = next(
        (p for p in projects if row and p.key == row.project_key),
        projects[0] if projects else None,
    )

    if block is None or not wanted or named is None or not named.instances:
        panel = env.get_template("_dispatch.html").render(
            started=False,
            detail="there is nothing here to build, or no checkout to build it in",
        )
        return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))

    instruction = "\n\n".join(
        [block.input, "The ideas this is about, as they were written down:"]
        + [f"- {idea.text}" for idea in wanted]
    )
    task = await store.queue_task(
        repo_key=named.key,
        cwd=named.instances[0].path,
        title=block.input[:60],
        instruction=instruction,
        source_kind="idea",
        # The ideas this task is *for*: what gets marked built when its agent finishes.
        source_ref=",".join(idea.id for idea in wanted),
        block_id=block.id,
    )
    result = await asyncio.to_thread(
        dispatch.start,
        dispatch.build_task(
            instruction,
            project=named.name,
            **await autostart.about(store, named.key),  # type: ignore[arg-type]
        ),
        cwd=named.instances[0].path,
        name=block.input[:40],
    )
    if result.started:
        await store.take_next_task(named.key)
        await store.task_started(task.id, result.agent_id)
    else:
        await store.task_failed(task.id, result.detail)

    panel = env.get_template("_dispatch.html").render(
        started=result.started,
        detail=result.detail,
        agent_id=result.agent_id,
        project=named.name,
    )
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/glossary", response_class=HTMLResponse)
async def add_term(request: Request) -> Response:
    """A word somebody uses, and what they mean by it (021-glossary.sql).

    An agent dispatched into a project does not have its vocabulary, and today that costs a
    paragraph of explanation in every instruction or a wrong guess. Everything written here goes
    into every briefing this console builds for this project.
    """
    form = await _form(request)
    key = form.get("key", "").strip()
    drop = form.get("drop", "").strip()
    if drop:
        await store.drop_term(drop)
    else:
        await store.add_term(
            repo_key=key if form.get("everywhere") != "yes" else "",
            term=form.get("term", ""),
            means=form.get("means", ""),
        )
    panel = await render_project(key)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/project-note", response_class=HTMLResponse)
async def set_project_note(request: Request) -> Response:
    """What anybody working in this project should know, besides the thing they were asked to do.

    The second entity next to the ideas, and the difference is what happens to it: an idea is a
    thing somebody *had* and will one day be built; this is a thing that is simply true and never
    will be. It goes into every agent this console starts here, verbatim, under a heading that
    says where it came from — an agent has to be able to tell a standing preference from the task.
    """
    form = await _form(request)
    key = form.get("key", "").strip()
    if key:
        await store.set_project_note(key, form.get("note", ""))
    panel = await render_project(key)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/explore", response_class=HTMLResponse)
async def set_exploring(request: Request) -> Response:
    """Let a project find its own work when its queue is empty (docs/adr/0008).

    A second switch rather than a wider one: arming says "start what I put here", this says "and
    when there is nothing, find something". Two decisions, made separately.
    """
    form = await _form(request)
    key = form.get("key", "").strip()
    if key:
        try:
            per_day = int(form.get("per_day", "3"))
        except ValueError:
            per_day = 3
        # The checkout goes with the switch: an exploration is the first task in a project and
        # has none to inherit a directory from (docs/adr/0008).
        rows, _ = await asyncio.to_thread(board)
        projects = shape(rows, await store.groups())
        named = next((project for project in projects if project.key == key), None)
        where = named.instances[0].path if named and named.instances else ""
        await store.explore(key, per_day=per_day, on=form.get("exploring") == "yes", cwd=where)
    panel = await render_project(key)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/projects/kicking", response_class=HTMLResponse)
async def set_kicking_here(request: Request) -> Response:
    """Switch every background session in one project into not being allowed to idle.

    docs/adr/0009 says "all of them" is a click repeated, not a wider switch — so this is exactly
    that: the same per-session rows the card's own button writes, written for the sessions that
    are in this project right now. A session started afterwards is a new decision and gets its own
    click, which is the property that keeps the switch a permission rather than a policy.
    """
    form = await _form(request)
    key = form.get("key", "").strip()
    on = form.get("kicking") == "yes"
    if key:
        rows, _ = await asyncio.to_thread(board)
        projects = shape(rows, await store.groups())
        named = next((project for project in projects if project.key == key), None)
        for row in [r for i in (named.instances if named else []) for r in i.rows]:
            if row.session.kind != "bg":
                continue
            await store.kick_session(
                row.session.session_id.split("-")[0],
                on=on,
                session_id=row.session.session_id,
                cwd=row.session.cwd,
            )
    panel = await render_project(key)
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.post("/plans", response_class=HTMLResponse)
async def manage_plans(request: Request) -> Response:
    """Declare a subscription, or forget one (025-subscriptions.sql).

    The limit is a number a person types, and the card says so: there is no account balance on
    this machine and nothing here to ask for one. Without a limit the card shows what this console
    observed and no percentage, which is honest and still useful.
    """
    form = await _form(request)
    drop = form.get("drop", "").strip()
    if drop:
        await store.drop_subscription(drop)
    else:
        try:
            limit = int(form.get("limit_tokens", "").replace("_", "").strip() or 0)
        except ValueError:
            limit = 0
        await store.add_subscription(
            name=form.get("name", ""),
            service=form.get("service", ""),
            limit_tokens=limit,
        )
    return HTMLResponse(await render_plans_page())


async def render_plans_page() -> str:
    """The page where subscriptions are declared and sessions are put on them."""
    rows, _ = await asyncio.to_thread(board)
    return env.get_template("plans.html").render(
        subscriptions=await store.subscriptions(),
        placed=await store.session_subscriptions(),
        rows=rows,
        plans=await board_plans(rows, await board_kicks()),
    )


@router.get("/plans", response_class=HTMLResponse)
async def plans_page() -> HTMLResponse:
    return HTMLResponse(await render_plans_page())


@router.post("/sessions/{session_id}/plan", response_class=HTMLResponse)
async def move_session(session_id: str, request: Request) -> Response:
    """Put one session on a subscription, or take it off.

    "Временно" is an hours field: after it the row is ignored and the session goes back to
    wherever it was, without anybody having to remember to move it back.
    """
    form = await _form(request)
    try:
        hours = int(form.get("hours", "").strip() or 0)
    except ValueError:
        hours = 0
    await store.move_session(
        session_id.split("-")[0],
        form.get("plan", "").strip(),
        until=now_ms() + hours * 3_600_000 if hours > 0 else None,
    )
    return HTMLResponse(await render_plans_page())


@router.post("/sessions/{session_id}/say", response_class=HTMLResponse)
async def say_to_session(session_id: str, request: Request) -> Response:
    """Answer a background session that is waiting for something, from its card.

    This is the case docs/adr/0002 was written *for*, not against: "a message to a session is a
    deliberate human act with a button behind it, never a side effect of a background loop." The
    words are somebody's, the click is theirs, and it goes nowhere else.

    The door is the one docs/adr/0009 found: `stop` keeps the conversation and `--bg --resume`
    continues it. A session in a terminal has no such door and the card offers no field.
    """
    form = await _form(request)
    said = form.get("text", "").strip()
    rows, _ = await asyncio.to_thread(board)
    row = next((r for r in rows if r.session.session_id == session_id), None)
    if row is None or not said:
        panel = env.get_template("_dispatch.html").render(
            started=False,
            detail="that session is not on the board any more" if row is None else "nothing typed",
        )
        return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))

    refused = nudge.kickable(row.session)
    if refused and row.session.kind not in nudge.KICKABLE_KINDS:
        # A session in a terminal. The refusal names the rule rather than the symptom.
        panel = env.get_template("_dispatch.html").render(started=False, detail=refused)
        return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))

    result = await asyncio.to_thread(
        dispatch.kick,
        row.session.session_id,
        said,
        cwd=row.session.cwd,
        agent_id=session_id.split("-")[0],
    )
    panel = env.get_template("_dispatch.html").render(
        started=result.started,
        detail=result.detail,
        agent_id=result.agent_id,
        project=row.session.project,
    )
    return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))


@router.post("/sessions/{session_id}/kicking", response_class=HTMLResponse)
async def set_kicking(session_id: str, request: Request) -> Response:
    """Switch one session into not being allowed to idle, or back out of it (docs/adr/0009).

    This is the explicit human click docs/adr/0002 requires, and what it buys is a standing
    permission rather than one message — which is the whole of what 0009 changes about that rule.
    Nothing here writes into a session that is working: the loop checks the registry every time,
    and `busy` is never continued.

    The full id and the checkout are recorded now, by the card that has them, because the first
    thing a kick does is stop the session — and a stopped session has no registry entry to read
    them back from.
    """
    form = await _form(request)
    on = form.get("kicking") == "yes"
    rows, _ = await asyncio.to_thread(board)
    row = next((r for r in rows if r.session.session_id == session_id), None)
    short = session_id.split("-")[0]
    if row is not None:
        await store.kick_session(
            short, on=on, session_id=row.session.session_id, cwd=row.session.cwd
        )
    elif not on:
        # Switching one off must work even for a session that has since gone: otherwise the row
        # stays armed forever and the loop keeps saying it is not running any more.
        await store.kick_session(short, on=False)

    panel = render_card("session", session_id, await store.groups())
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


@router.post("/blocks/{block_id}/as-idea", response_class=HTMLResponse)
async def make_it_an_idea(block_id: str, request: Request) -> Response:
    """ "That was a thought, not an instruction" — one click, on the block that got it wrong.

    The run that reads what was typed is a run, and it is wrong sometimes; the console's answer to
    that is the same as everywhere else in this program — the correction is visible, it is one
    click, and it does not need anybody to retype what they said (docs/04-threads-and-blocks.md).

    What it does not do is stop an agent that was already started. That has its own button, right
    beside it, because "record this as an idea" and "stop what is running" are two decisions and
    somebody may well want only the first.
    """
    block = await store.block(block_id)
    if block is None:
        return HTMLResponse(await render_blocks(), status_code=404)
    if block.kind != "idea":
        rows, _ = await asyncio.to_thread(board)
        await block_runs.record_idea(store, block, rows)
    if _wants_fragment(request):
        return HTMLResponse(await render_blocks())
    return RedirectResponse("/", status_code=303)


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
    # Registered in the tracker: it is somebody's queue now, not a thought waiting to be had, so
    # it leaves the column. The inbox keeps it with the key it was filed as (docs/05-ideas.md).
    await store.set_idea_state(idea_id, "done")
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
    if action not in ("keep", "drop", "done", "summary", *DRAFT_KINDS):
        # An action this program does not have is a mistake somewhere, not something to redirect
        # away from quietly — that is how a typo becomes a mystery.
        # The segment is not echoed back: reflecting an unvalidated path into a response is a
        # habit worth not having, even where the content type makes it harmless.
        return PlainTextResponse("no such action", status_code=404)

    # The templates hide a button that does not apply; the route has to mean it. Keeping an idea
    # that was already promoted quietly walked it backwards through its own four states.
    allowed = {
        "new": {"keep", "drop", "done", "summary"},
        "kept": {"drop", "done", "summary", *DRAFT_KINDS},
        "promoted": {"done", "summary", *DRAFT_KINDS},
        "dropped": {"keep", "summary"},
        # Built is not final: a human who finds it was not, after all, says so with Keep.
        "done": {"keep", "summary"},
    }[idea.state]
    if action not in allowed:
        return PlainTextResponse(f"an idea that is {idea.state} cannot do that", status_code=409)

    if action in ("keep", "drop", "done"):
        reached: IdeaState = (
            "kept" if action == "keep" else "dropped" if action == "drop" else "done"
        )
        await store.set_idea_state(idea_id, reached)
        if reached == "kept":
            # "Каждая идея при апруве преобразуется как минимум в часть документации." Keeping an
            # idea is somebody saying it is worth doing, and the smallest useful thing to have
            # afterwards is it written up — so the proposal is drafted there and then instead of
            # waiting for a second click nobody makes.
            #
            # The *maximum* the idea asks for — a list of Jira tickets — stays a click, and that
            # is docs/adr/0005 unchanged: filing into somebody else's queue is a door a human
            # opens. The draft that would be filed is ready by the time they reach for it.
            if block_runs.runs.running:
                await block_runs.draft(store, idea, "proposal")
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
