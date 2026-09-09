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
import hashlib
import io
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup, escape

from agent_desk import (
    allowed,
    because,
    branching,
    carrying,
    checking,
    combining,
    comparing,
    connectors,
    dispatch,
    handling,
    land,
    pasted,
    peer,
    process,
    roles,
    room,
    spread,
    starting,
    telling,
    ties,
    tooling,
    tracker,
)
from agent_desk import secrets as kept
from agent_desk.answer import session as answer_session
from agent_desk.config import settings
from agent_desk.ideas import appraise, bench, chart, describe, inbox, meeting, waking
from agent_desk.observe import attach, folder, reading, registry, transcript
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
    BenchCard,
    Group,
    Idea,
    IdeaState,
    Kicking,
    ProjectLink,
    Store,
    Task,
    TemplateLine,
    TemplateStep,
    Thread,
)
from agent_desk.tracker import jira
from agent_desk.web import autostart, blockers, engine, plans
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


def _comes_back(idea: Idea) -> str:
    """When a deferred idea is due, in the words somebody would use (031-deferred.sql).

    Both halves when both were said: "завтра, когда гейт позеленеет" is one moment, and showing
    only the clock half of it would be a card that says a thing will happen at nine which will
    not happen at nine.
    """
    wake = waking.Wake(at=idea.wakes_at, when=idea.wakes_when)
    return wake.says


def _blocker_is(kind: str) -> str:
    """What a blocker is, in the words somebody reading the column would use.

    `kind` is this program's word for the thing — it keys the map, the styling and the id — and
    printing it on a card asked the reader to learn six of them.
    """
    return blockers.PLAINLY.get(kind, kind)


def _stamped(name: str) -> str:
    """`/static/<name>` with a stamp of what is in the file.

    Without it a browser holds the last stylesheet it saw and keeps rendering from it: the console
    was serving a fixed `console.css` and showing the broken one, because nothing in the URL had
    changed. Found by watching four panels stay on screen after the rule that hides them was
    already in the file being served.

    The stamp is the content, not the clock, so an unchanged file keeps its URL and stays cached —
    which is the whole point of caching it. Read once, at import: this is a single-user local tool
    and the process restarts when the file changes.
    """
    where = Path(__file__).parent / "static" / name
    try:
        return f"/static/{name}?v={hashlib.sha256(where.read_bytes()).hexdigest()[:12]}"
    except OSError:
        # A missing file is a page that says so, not a page that will not render.
        return f"/static/{name}"


env.globals["stamped"] = _stamped
env.filters["blocker_is"] = _blocker_is
env.filters["comes_back"] = _comes_back
env.filters["tokens"] = _tokens
env.filters["plainly"] = _plainly
env.filters["prose"] = _prose
env.filters["ago"] = _ago
env.filters["clock"] = _clock
env.filters["at"] = _at
# What stopped, and what would change it (agent_desk/telling.py). A filter rather than a value
# prepared for the template, because a failure can appear on a block, on a task and on a card, and
# three places preparing the same pair is three places for one of them to drift.
env.filters["stopped"] = telling.stopped
# What this console decided a message was, in words rather than as a class on the article.
env.filters["taken_as"] = telling.taken_as


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


@dataclass(frozen=True)
class Spent:
    """What today has cost and how close that is to the ceiling.

    Three states rather than a number, because the number alone is not the reading: the same
    `$24.90` means nothing on a day with no ceiling and means "the next question is the last one"
    under a ceiling of twenty-five.
    """

    usd: float
    ceiling: float

    @property
    def stopped(self) -> bool:
        return bool(self.ceiling) and self.usd >= self.ceiling

    @property
    def close(self) -> bool:
        """Worth mentioning the ceiling. Below this the ceiling is noise beside the number, and a
        counter that recites a limit nobody is near is one people stop reading."""
        return bool(self.ceiling) and self.usd >= self.ceiling * 0.5


async def board_spent() -> Spent:
    return Spent(usd=await store.spent_today(), ceiling=settings.daily_usd)


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
    spent: Spent | None = None,
) -> str:
    """The fragment the page holds and every server-sent event replaces.

    `spent` is read where the store is and handed in, because this runs in a thread. Absent means
    the counter is simply not rendered, which is deliberate: a caller that forgot to read it should
    show nothing rather than a confident `$0.00`, which is a different claim entirely.
    """
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
        # What today has cost (043-spending.sql).
        spent=spent,
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
        # And what a run that has not said anything yet is doing (agent_desk/web/blocks.py).
        doing=block_runs.DOING,
        # A rearranging answer, said in words. What it stored is the actions; this is what somebody
        # scrolling back through the conversation reads instead of a blob (agent_desk/handling.py).
        # A process a message described, as the words for it and the cards it made.
        drawn={
            block.id: telling.read_drawn(block.answer or "")
            for block in rows
            if block.kind == "drawing" and block.answer
        },
        arranged={
            block.id: handling.as_words(handling.read_json(block.answer or ""))
            for block in rows
            if block.kind == "handling" and block.answer
        },
        # A run that was understood and is waiting to be pressed. Empty for one that started, which
        # is every run of a drawing made only of prompts.
        will_run={
            block.id: telling.read_will_run(block.answer or "")
            for block in rows
            if block.kind == "running" and block.answer
        },
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
    # "По ним можно сортироваться." A proposal nobody has looked at is a different kind of thing
    # from a note somebody made, and finding all of one sort is the first thing anybody does.
    ("proposed", "what the desk suggested first"),
    ("mine", "what I wrote first"),
)
IDEA_SORT_KEY = "ideas.sort"
# Whether the pool is showing what was set aside instead of what is live. In the store for the
# same reason the sort is: the column is replaced by a stream every couple of seconds, and a
# filter that resets two seconds after it is set is a filter that looks broken.
ASIDE_KEY = "ideas.aside"
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
    if how == "proposed":
        return sorted(roots, key=lambda idea: 0 if idea.author == "desk" else 1)
    if how == "mine":
        return sorted(roots, key=lambda idea: 0 if idea.author == "human" else 1)
    return roots


async def render_blockers() -> str:
    """The top of the right column: what has stopped (agent_desk/web/blockers.py)."""
    only = await store.setting(FOCUS_KEY)
    return env.get_template("_blockers.html").render(
        found=await blockers.blockers(store, only), only=only
    )


UNDO_SAYS = {"drop": "discarded", "done": "marked built", "keep": "kept"}


async def _undone() -> dict[str, str]:
    """What the last action was, in words, or nothing when there is nothing to put back."""
    idea_id, was, did = await _undo_says()
    if not idea_id or did not in UNDO_SAYS:
        return {}
    idea = await store.idea(idea_id)
    return (
        {"id": idea_id, "says": UNDO_SAYS[did], "summary": idea.summary, "was": was}
        if idea is not None and idea.state != was
        else {}
    )


def _said_about(said: dict[str, str]) -> dict[str, str]:
    """The sentences, keyed by idea id rather than by card name, which is what the column wants."""
    return {name.split(":", 1)[1]: what for name, what in said.items()}


async def render_ideas() -> str:
    """The bottom half of the right column: what has been written down.

    Dropped ideas are not shown here. The inbox keeps them — an idea's history is part of what the
    notebook is for — but a column somebody glances at is about what is still live.
    """
    how = await store.setting(IDEA_SORT_KEY, "newest")
    only = await store.setting(FOCUS_KEY)
    # "Пропадает из списка идей, можно жмякнуть фильтр, чтоб показало отменённые." Setting a
    # proposal aside is `dropped` — the word already there for "we decided not to" — so the filter
    # is over the state that already exists rather than a fifth one meaning the same thing.
    aside = await store.setting(ASIDE_KEY) == "yes"

    def shown(idea: Idea) -> bool:
        return idea.state == "dropped" if aside else idea.state not in ("dropped", "done")

    ideas = [idea for idea in await store.ideas() if shown(idea)]
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
        # And the evidence, where there is any: a card that *knows* an idea was built must not
        # look like one that merely suspects it.
        said_about=_said_about(await store.cards_said([f"idea:{idea.id}" for idea in ideas])),
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
        # What each project is called, so "build it" can say where it would land rather than
        # asking somebody to recognise a repository key.
        named_projects=dict(await _project_choices()),
        # Whether it is showing what was set aside, so it can say so and offer the way back.
        aside=aside,
        # The last thing that was done, so the column can offer to put it back. Named here rather
        # than worked out in the template: which of the three words to show is a fact about what
        # happened, not about how it is drawn.
        undo=await _undone(),
    )


async def render_inbox() -> str:
    """Kept ideas, each carrying where it came from (docs/05-ideas.md)."""
    ideas = await store.ideas()
    drafts = await store.drafts_by_idea()
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
    chats = await open_chats()
    # The chat the page opens on, which `_tabs.html` marks with `loop.first`. Its bench is the one
    # rendered into the page; every other chat's is fetched when somebody switches to it.
    opening = chats[0].id if chats else ""
    return env.get_template("board.html").render(
        threads=chats,
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
            spent=await board_spent(),
        ),
        projects=projects,
        message=message,
        blocks=await render_blocks(),
        poll=settings.registry_poll_seconds,
        # The workbench as it was left. Rendered into the page rather than fetched by it, because
        # the first thing the script does after the page opens is write the bench back — and a
        # write that overtook a fetch would save an empty surface over a full one (040-bench.sql).
        kept=[card.model_dump() for card in await store.bench_cards(opening)],
        # And which of them the enquiry starts from, on the same terms and for the same reason:
        # the mark belongs to a card that is already on the surface (050).
        began=await store.began(opening),
        # Which column each kind of card belongs in when the bench is laid out again. From
        # `ideas/bench.py`, which is where the workbench diagram reads the same order — a copy in
        # the script would be a second place to be wrong, silently.
        columns={"of": bench.COLUMN, "beside": bench.BESIDE},
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


@router.post("/cards/role", response_class=HTMLResponse)
async def set_card_role(request: Request) -> Response:
    """Say what a card is in the process being described (033-card-roles.sql).

    Five names and nothing else is accepted. The point of five is that a diagram can be read
    without reading it, and a sixth name typed into a form is how that becomes a free-text label
    with a shape attached to it.
    """
    form = await _form(request)
    name = form.get("name", "").strip()
    role = form.get("role", "").strip()
    # Empty is allowed and means "back to whatever this kind naturally is". Anything else that is
    # not one of the five is refused rather than stored and quietly ignored at render time.
    if name and (not role or roles.is_a_role(role)):
        await store.set_card_role(name, role)
    return HTMLResponse("", status_code=204)


@router.get("/cards/roles", response_class=JSONResponse)
async def card_roles() -> JSONResponse:
    """Every role anybody has chosen, and the five they can choose from.

    The page asks for both together because it needs both together, and because the five are
    defined in `agent_desk/roles.py` — a list of them copied into the stylesheet or the script
    would be a second place for them to be wrong.
    """
    return JSONResponse(
        {
            "roles": await store.card_roles(),
            "naturally": roles.NATURALLY,
            "says": {
                name: {
                    "says": one.says,
                    "means": one.means,
                    "shape": one.shape,
                    # What a card of this role is asked, so the page can draw the form. Defined in
                    # agent_desk/roles.py and sent, never listed twice — the same rule the five
                    # names follow, and the one that matters more, because a field the page knows
                    # about and the store does not is a field that silently fails to save.
                    "fields": [
                        {
                            "name": field.name,
                            "says": field.says,
                            "asks": field.asks,
                            "lines": field.lines,
                            "needed": field.needed,
                        }
                        for field in roles.fields_of(name)
                    ],
                }
                for name, one in roles.ROLES.items()
            },
            "fields": await store.card_fields(),
        }
    )


@router.post("/cards/field", response_class=JSONResponse)
async def set_card_field(request: Request) -> JSONResponse:
    """Write one of the fields a card's role asks for (035-card-fields.sql).

    The field must be one the role actually has. That check is the whole difference between this
    and a notes table: *"поле, которое можно назвать как угодно, — это снова свободный текст, а
    свободный текст движок исполнить не может."*

    The role is taken from the form because the page knows it — including the role a card was
    just given, before anything has been stored for it — but it is validated the same way as
    everywhere else, so a name that is not one of the five reaches nothing.
    """
    form = await _form(request)
    name = form.get("name", "").strip()
    role = form.get("role", "").strip()
    field = form.get("field", "").strip()
    if not name or not roles.is_a_role(role) or not roles.is_a_field(role, field):
        return JSONResponse({"kept": False}, status_code=400)
    await store.set_card_field(name, field, form.get("value", ""))
    return JSONResponse({"kept": True})


@router.get("/cards/folder", response_class=HTMLResponse)
async def folder_card(id: str = "") -> HTMLResponse:
    """A folder on this machine, as a card: what is in it, and what each thing is for.

    A link, not a copy — nothing is uploaded and no file is opened. What travels with a message is
    the list, which is why this is safe to offer for a directory that may hold anything.
    """
    found = folder.read(id)
    said = ""
    if found.ok:
        said = await describe.describe(
            store, f"folder:{found.path}", "folder on somebody's machine", folder.about(found)
        )
    return HTMLResponse(
        env.get_template("_card_folder.html").render(folder=found, said=said),
        status_code=200 if found.ok else 404,
    )


@router.post("/cards/file/read", response_class=HTMLResponse)
async def let_a_file_be_read(request: Request) -> Response:
    """One click, one file, recorded (055).

    "Это отдельное разрешение, которое человек даёт явно, а не побочный эффект просьбы." The
    request that would use the contents does not grant this and cannot: the grant is a button
    somebody pressed, on a card naming the file, saying what pressing it does.

    A credential is refused here as well as in the reader. Two checks for one rule on purpose —
    this one keeps the row out of the table, so "which files may this console open" never has a
    wrong answer in it, and the reader's holds even if a row appeared by another route.
    """
    path = str((await _form(request)).get("path", "")).strip()
    if not path or reading.is_a_credential(Path(path).expanduser()):
        return HTMLResponse("", status_code=400)
    await store.let_it_be_read(path)
    return HTMLResponse("", status_code=204)


@router.post("/blocks/{block_id}/project", response_class=HTMLResponse)
async def start_a_project(block_id: str, request: Request) -> Response:
    """Bring the repository this message pointed at onto this machine, and queue the first task.

    Two acts and this is the first of them: the work is queued, not started. Cloning a repository
    because somebody typed an address would be the automatic queue docs/adr/0007 exists to refuse,
    and starting an agent on it would be that twice.

    The clone goes under `data_dir`, the one tree this program writes to. A checkout this console
    made is not one of the repositories it reads over somebody's shoulder — the second of the five
    rules stays exactly as strict as it was (agent_desk/starting.py).
    """
    block = await store.block(block_id)
    if block is None or not block.from_repo:
        return HTMLResponse(_a_sentence("There is no repository in that message."), status_code=404)

    into = starting.where(settings.data_dir, block.from_repo)
    token = kept.get(pasted.name_for((block.from_repo,)))
    made = await asyncio.to_thread(starting.clone, block.from_repo, into, token=token)
    if not made.ok:
        return HTMLResponse(_a_sentence(f"Nothing was started: {made.detail}"))

    await store.queue_task(
        repo_key=made.repo_key,
        cwd=made.cwd,
        title=f"first work in {made.name}",
        instruction=starting.first_task(block.input, block.from_repo),
        source_kind="block",
        block_id=block.id,
    )
    # Its own settings panel, which is where the queue and the button that starts it are. Landing
    # somebody on the project they just made beats telling them it exists.
    return HTMLResponse(await render_project(made.repo_key))


def _a_sentence(said: str) -> str:
    """One line into the panel every control answers into. A refusal is a sentence, not a page."""
    return f'<p class="small">{escape(said)}</p>'


@router.get("/room", response_class=JSONResponse)
async def how_much_could_run() -> JSONResponse:
    """How many agents could be started right now, and why that is the number (agent_desk/room.py).

    Every reason comes from `autostart.why_not`, which is the function the loop itself asks. A
    second opinion computed here would be a console explaining a decision that was made somewhere
    else, and the two would disagree the first time either changed.
    """
    rows, _ = await asyncio.to_thread(board)
    projects = shape(rows, await store.groups())
    live = await asyncio.to_thread(autostart.live_agents)
    seats = []
    for project in projects:
        why = await autostart.why_not(store, project.key, live)
        seats.append(
            room.Seat(
                repo_key=project.key,
                name=project.name,
                free=not why,
                why=why,
                waiting=len(
                    [one for one in await store.tasks(repo_key=project.key) if one.waiting]
                ),
            )
        )
    found = room.how_many(seats)
    return JSONResponse({"at_once": found.at_once, "said": found.said, "lines": found.lines})


@router.get("/cards/{kind}/parts", response_class=JSONResponse)
async def parts_of_a_card(kind: str, id: str = "") -> JSONResponse:
    """What is inside a card whose insides are not on the board.

    "Тот же механизм раскрытия, но через сеть: у коннектора спрашивают, что у него внутри, уровень
    за уровнем." A project's checkouts and sessions are already rendered in the left column, so the
    page reads them from there; a connector's are behind somebody else's API, and the page has to
    ask.

    Two levels, and they are the two the idea names. A Jira connector opens into the columns of the
    board it points at; a column opens into the tickets standing in it. Read-only throughout
    (docs/adr/0010): opening a column moves nothing and creates nothing.

    A kind with nothing behind it answers with an empty list rather than a 404. "Nothing inside
    this one" is a true answer about a connector to something this console cannot read, and the
    page hides the control on it.
    """
    if kind == "connector":
        repo_key, _, name = id.partition("::")
        return JSONResponse({"parts": await _columns_of(repo_key, name)})
    if kind == "column":
        repo_key, sep, status = id.rpartition("::")
        rows = await store.board_tickets(repo_key) if sep else []
        return JSONResponse(
            {
                "parts": [
                    {"kind": "ticket", "id": f"{repo_key}::{one.key}", "label": one.summary}
                    for one in rows
                    if (one.status or "no column") == status
                ]
            }
        )
    return JSONResponse({"parts": []})


async def _columns_of(repo_key: str, name: str) -> list[dict[str, str]]:
    """The columns of the board a connector points at, as cards.

    A column is a status: that is what a Jira board column *is*, and reading the agile API for the
    board's own column names would be a second request for a second version of the same list —
    which would then disagree with the tickets, because those come back with statuses.

    What this can show is what this console reads, which is the unfinished part of a board
    (`jira.WANTED_STATUSES`). A board with a Done column has one here only if something unfinished
    is standing in it, and the card says so rather than implying the board has four columns.
    """
    link = next((one for one in await store.links(repo_key) if one.name == name), None)
    if link is None or jira.destination_of(link.url, link.token_env) is None:
        return []
    rows = await store.board_tickets(repo_key)
    if not rows:
        # Nothing read yet. Read it now — opening a connector is asking what is in it, and an
        # empty answer from an unread board is the wrong answer to that question.
        _, why = await block_runs.read_tickets_now(store, repo_key)
        if why:
            return []
        rows = await store.board_tickets(repo_key)
    seen: dict[str, int] = {}
    for one in rows:
        seen[one.status or "no column"] = seen.get(one.status or "no column", 0) + 1
    return [
        {
            "kind": "column",
            "id": f"{repo_key}::{status}",
            "label": f"{status} · {count} ticket{'' if count == 1 else 's'}",
        }
        for status, count in sorted(seen.items())
    ]


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
                idea=idea,
                said=await describe_card("idea", id) if idea else "",
                projects=await _project_choices(),
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
    if kind == "step":
        # A card that is only a card. What it *is* lives in its role and that role's fields, both
        # of which the console draws onto every card — so this is almost empty on purpose.
        one = await store.step_card(id)
        return HTMLResponse(
            env.get_template("_card_step.html").render(card=one),
            status_code=200 if one else 404,
        )
    if kind == "task":
        # A ticket. It has been draggable out of the right-hand column since that column existed
        # and rendered "could not read this one" on arrival, because `render_card` knows the four
        # kinds that come off the board and a ticket comes out of the store.
        ticket = await store.task(id)
        return HTMLResponse(
            env.get_template("_card_task.html").render(card=ticket),
            status_code=200 if ticket else 404,
        )
    if kind == "pull":
        # `<project key>::#12`. The project key is half of it because a pull request number means
        # nothing outside the repository it belongs to, and `::` is the separator the connector
        # cards already use for exactly this (052-a-pull-request-is-a-thing.sql).
        repo_key, _, number = id.rpartition("::")
        found = (
            await store.pull(repo_key, int(number.lstrip("#")))
            if repo_key and number.lstrip("#").isdigit()
            else None
        )
        return HTMLResponse(
            env.get_template("_card_pull.html").render(card=found),
            status_code=200 if found else 404,
        )
    if kind == "ticket":
        # `<project key>::API-14`, split from the right for the reason the pull cards are: a
        # project key contains colons (053-a-ticket-is-a-thing-too.sql).
        repo_key, sep, key = id.rpartition("::")
        row = await store.board_ticket(repo_key, key) if sep and repo_key and key else None
        return HTMLResponse(
            env.get_template("_card_ticket.html").render(card=row),
            status_code=200 if row else 404,
        )
    if kind == "column":
        repo_key, sep, status = id.rpartition("::")
        rows = [
            one
            for one in (await store.board_tickets(repo_key) if sep else [])
            if (one.status or "no column") == status
        ]
        return HTMLResponse(
            env.get_template("_card_column.html").render(
                status=status, tickets=rows, repo_key=repo_key
            ),
            status_code=200 if sep and status else 404,
        )
    if kind == "file":
        # A file is a path, so the id is a path — which is why the id travels as a query parameter
        # for every card and not as a path segment.
        allowed = await store.may_be_read(id)
        return HTMLResponse(
            env.get_template("_card_file.html").render(
                path=id,
                name=id.rsplit("/", 1)[-1],
                allowed=allowed,
                said=reading.read_file(id) if allowed else reading.Said(False),
            ),
            status_code=200,
        )
    if kind == "button":
        # A card that is a request. Its prompt is on the card and editable there, because a button
        # whose request you cannot read is a button you press once (059).
        made = await store.button_card(id)
        return HTMLResponse(
            env.get_template("_card_button.html").render(card=made),
            status_code=200 if made else 404,
        )
    if kind == "check":
        # A card hung on an output. What it checks for is on the card and editable there, for the
        # same reason a button's request is: a control whose condition you cannot read is one
        # nobody trusts the verdict of (062).
        checked = await store.check_card(id)
        return HTMLResponse(
            env.get_template("_card_check.html").render(card=checked),
            status_code=200 if checked else 404,
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
        # A project added by pointing at a repository is an address and nothing else, and this is
        # the press that needs a directory. Cloning here rather than at the moment the address was
        # typed is the whole of the difference: adding a project records where one lives
        # (agent_desk/observe/attach.py), and this is a person asking for an agent in it, which is
        # the click docs/adr/0006 requires. The checkout goes under `data_dir` — a checkout this
        # console made is not one it reads over somebody's shoulder, so the second of the five
        # rules is untouched (agent_desk/starting.py).
        address = next((one.url for one in await store.links(key) if one.url), "")
        if not address:
            panel = env.get_template("_instance.html").render(
                stage="failed",
                detail="that project has no checkout on this machine and no address to clone from",
                key=key,
            )
            return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))
        made = await asyncio.to_thread(
            starting.checkout,
            settings.data_dir,
            address,
            token=kept.get(pasted.name_for((address,))),
        )
        if not made.ok:
            panel = env.get_template("_instance.html").render(
                stage="failed", detail=f"it could not be brought here: {made.detail}", key=key
            )
            return HTMLResponse(panel if _wants_fragment(request) else await render_page(panel))
        cwd = made.cwd
        # The repository's own name when the board has never seen this project: a panel that says
        # "started in " and stops is a panel that has forgotten what it just did.
        project_name = named.name if named is not None else made.name
    else:
        cwd = named.instances[0].path
        project_name = named.name
    needed = [one.name for one in await store.env(key)]
    result = await asyncio.to_thread(
        dispatch.start,
        dispatch.introduce(who, project=project_name, doing=doing, env_names=needed),
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
        name=project_name,
    )
    if _wants_fragment(request):
        return HTMLResponse(panel)
    return HTMLResponse(await render_page(panel))


@router.get("/workbench/combining", response_class=JSONResponse)
async def what_a_combine_asks(thread: str = "") -> JSONResponse:
    """What dragging one card onto another will ask on this bench, and whether anybody set it.

    `its_own` is the difference between "this is what it asks" and "this is what somebody chose",
    which is the difference a panel offering to change it has to draw.
    """
    said = await store.combining(thread)
    return JSONResponse({"said": combining.rule(said), "its_own": bool(said.strip())})


@router.get("/workbench/made", response_class=JSONResponse)
async def what_these_two_already_made(thread: str = "", pair: str = "") -> JSONResponse:
    """Whether these two cards have already made something under the rule in force.

    "Иначе это не мир, а генератор случайностей: собрал то же самое и получил другое." Asked before
    the combine rather than answered after it, because the point is not to spend the call twice —
    and because what somebody wants back is the card they already have, not a second one saying
    almost the same thing beside it.
    """
    two = [one for one in pair.split(",") if one]
    if len(two) != 2:
        return JSONResponse({})
    said = combining.rule(await store.combining(thread))
    before = await store.combined_before(thread, two, said)
    if before is None:
        return JSONResponse({})
    return JSONResponse({"block": before.id, "said": (before.answer or "")[:200]})


@router.get("/workbench/shelf", response_class=JSONResponse)
async def what_this_bench_has_made(thread: str = "") -> JSONResponse:
    """Everything two cards have made here, newest first — the shelf it all goes on.

    Each row carries the name of its answer card, so a press can bring the card back rather than
    ask the same pair a second time. The first line of the answer is the label: what a made thing
    is called is what it says, and a name somebody has to invent for each one is a name nobody
    types.
    """
    made = []
    for block in await store.made_here(thread):
        first = (block.answer or "").strip().splitlines()
        made.append(
            {
                "card": f"answer:{block.id}",
                "label": (first[0] if first else "an answer")[:70],
                "from": [one for one in block.made_from.split(",") if one],
            }
        )
    return JSONResponse({"made": made})


@router.post("/workbench/combining", response_class=JSONResponse)
async def set_what_a_combine_asks(request: Request) -> JSONResponse:
    """Change it, or clear it back to what the console asks by default.

    Empty is how somebody undoes this, and it is the same gesture as never having set it: the row
    goes, and the default comes from one place (agent_desk/combining.py).
    """
    form = await _form(request)
    thread = form.get("thread", "").strip()
    if not thread:
        return JSONResponse({"why": "Open a chat first — a rule belongs to one workbench."})
    await store.combine_with(thread, form.get("said", "")[: combining.MOST_CHARS])
    said = await store.combining(thread)
    return JSONResponse({"said": combining.rule(said), "its_own": bool(said.strip())})


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
                    await board_spent(),
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
                spent=await board_spent(),
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
                spent=await board_spent(),
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
    # Sent by a button on the workbench rather than typed. The bench draws no card for the question
    # then: pressing a button is "как будто бы мы его вписали в поле ввода, только без создания
    # карточки запроса" (059-a-card-that-is-a-button.sql).
    by_button = str(form.get("button", "")).strip() == "yes"
    # Two cards dragged together on the workbench. Separate from `targets`, which says what the
    # question is *about* — every message has those. This says what the third card was made out of,
    # and only a combine has it (060-what-two-cards-made.sql).
    combined = [one for one in form.get("made_from", "").split(",") if one]
    # Which gesture this was, or "" for something somebody typed. Named rather than inferred from
    # the shape of the form: the flag decides whether the classifier ever sees this text, and that
    # is the branch that can start an agent — it should not hang on a field's length.
    gesture = form.get("gesture", "").strip()
    # A combine's words are the bench's rule, and the page does not get a say in them. The gesture
    # sends two card names; what putting two cards together *means* is a thing somebody set once
    # and can change (061-the-rule-a-combine-follows.sql). Read here rather than sent by the page
    # so there is one copy of it, and so a rule changed in one tab is the rule the next drag in
    # another tab follows.
    if gesture == "combine" and len(combined) == 2:
        typed = combining.rule(await store.combining(form.get("thread", "").strip()))
    if typed:
        rows, _ = await asyncio.to_thread(board)
        # The board is shaped before the question is aimed, and the *shaped* rows are what travels:
        # the target the human picked is a card, and only a row that has been through `shape`
        # knows which card it is under.
        projects = shape(rows, await store.groups())
        stamped = [row for p in projects for i in p.instances for row in i.rows]
        made = await block_runs.submit(
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
            # Named by the gesture rather than carried by the message, which is what lets a result
            # card be one of the two: `on_the_bench` leaves the halves of an exchange out unless
            # something pointed at them.
            made_from=combined if gesture else (),
            a_gesture=bool(gesture),
        )
        if by_button:
            await store.sent_by_a_button(made.id)
        if len(combined) == 2:
            await store.made_out_of(made.id, combined)
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
    # And the lines between cards that came from different places, named the way whoever recorded
    # them named it — a board's own "blocks", this console's own "filed as" (054). Never a line
    # drawn because two cards mention the same string.
    ties += bench.recorded_ties(
        picked,
        ticket_links=await store.ticket_links(),
        tasks=await store.tasks(limit=400),
        filings=await store.filings(),
    )
    return HTMLResponse(json.dumps(ties), media_type="application/json")


@router.post("/workbench/tie", response_class=JSONResponse)
async def tie_cards(request: Request) -> JSONResponse:
    """Draw a line between two cards, or change one (034-card-ties.sql).

    The kind is chosen by the page from the roles at both ends and can be overridden; anything
    that is not one of the five is refused rather than stored, for the same reason a sixth role
    is: five words with a meaning each is a language, and a free-text label with an arrow on it
    is a note.
    """
    form = await _form(request)
    from_name = form.get("from", "").strip()
    to_name = form.get("to", "").strip()
    kind = form.get("kind", "").strip() or ties.ORDINARILY
    if not from_name or not to_name or not ties.is_a_kind(kind):
        return JSONResponse({"drawn": False}, status_code=400)
    await store.tie_cards(
        from_name=from_name,
        to_name=to_name,
        kind=kind,
        says=form.get("says", "").strip(),
        thread_id=form.get("thread", "").strip(),
    )
    return JSONResponse({"drawn": True})


@router.post("/workbench/untie", response_class=JSONResponse)
async def untie_cards(request: Request) -> JSONResponse:
    form = await _form(request)
    await store.untie_cards(form.get("id", "").strip(), thread_id=form.get("thread", "").strip())
    return JSONResponse({"gone": True})


@router.get("/workbench/lines", response_class=JSONResponse)
async def workbench_lines() -> JSONResponse:
    """Every line somebody has drawn, and the five kinds a line can be.

    Both together, and the vocabulary from `agent_desk/ties.py` rather than a copy in the script —
    the same argument as the roles: a second list is a second place to be wrong, silently.

    Which of these actually get drawn is the page's business: a line with one end off the bench
    explains nothing, and this has no way of knowing what somebody has put on it.
    """
    return JSONResponse(
        {
            "lines": [
                {
                    "id": tie.id,
                    "from": tie.from_name,
                    "to": tie.to_name,
                    "kind": tie.kind,
                    "says": tie.says,
                }
                for tie in await store.card_ties()
            ],
            "kinds": {
                name: {
                    "says": one.says,
                    "means": one.means,
                    "wants_words": one.wants_words,
                    "one_way": one.one_way,
                }
                for name, one in ties.KINDS.items()
            },
            "from_role": ties.FROM_ROLE,
            "into_role": ties.INTO_ROLE,
            "ordinarily": ties.ORDINARILY,
        }
    )


@router.post("/cards/leave", response_class=JSONResponse)
async def set_card_leave(request: Request) -> JSONResponse:
    """Say what one step is allowed to do (036-step-memory.sql).

    The whole set as it now stands, not a change to one switch: a merge would make turning a
    permission *off* impossible to express, and a permissions screen where things can only be
    granted is not one.
    """
    form = await _form(request)
    name = form.get("name", "").strip()
    given = [one for one in form.get("leave", "").split(",") if allowed.is_allowed(one)]
    if not name:
        return JSONResponse({"kept": False}, status_code=400)
    await store.set_card_leave(name, given)
    return JSONResponse({"kept": True, "leave": given})


@router.post("/workbench/kept", response_class=JSONResponse)
async def keep_bench(request: Request) -> JSONResponse:
    """What is on the workbench right now, so that it is still there after a reload.

    The whole surface, not a change to it (040-bench.sql). The page is the only thing that knows
    what is on the bench; sending the whole set is the smallest message that can say "this card is
    gone", and a diff would need the page to remember what the store last saw — a second copy of
    the truth, kept in the place least able to keep it.

    A row that does not parse is dropped rather than failing the write. Losing one card's position
    is a card in the wrong place; refusing the write is the whole arrangement lost, which is the
    failure this route exists to stop.

    The stacking order is the order the cards arrive in, not a number they carry. The page has them
    in surface order already, and a card that had to name its own place could name one twice.

    The position is read out of `at`, which is where the page keeps it, so what arrives here is
    what the page's own reading of its bench returns and nothing reshapes it in between. The first
    version of this did reshape it, disagreed with itself about whether `at` was a position or a
    clock, and dropped every card in every message — correctly, quietly, and for weeks if nobody
    had opened a browser.
    """
    said = await request.json()
    thread_id = str(said.get("thread", "")) if isinstance(said, dict) else ""
    cards = []
    for place, one in enumerate(said.get("cards", []) if isinstance(said, dict) else []):
        try:
            cards.append(
                BenchCard(
                    name=str(one["name"])[:200],
                    kind=str(one["kind"])[:40],
                    card_id=str(one["id"])[:200],
                    label=str(one.get("label", ""))[:200],
                    x=int(one["at"]["x"]),
                    y=int(one["at"]["y"]),
                    shown=str(one.get("shown", "hint"))[:20],
                    spent=bool(one.get("spent")),
                    by_hand=bool(one.get("by_hand")),
                    came=str(one.get("came", ""))[:120],
                    came_at=int(one.get("came_at", 0)),
                    ord=place,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    # Whether somebody moved a card, which is the one part of this the store cannot work out for
    # itself — the console lays cards out again whenever one grows to fit its body, so a coordinate
    # that changed is not evidence that anybody did anything (041-bench-undo.sql).
    moved = bool(said.get("moved")) if isinstance(said, dict) else False
    await store.keep_bench(cards, thread_id=thread_id, moved=moved)
    return JSONResponse({"kept": len(cards)})


@router.get("/workbench/kept", response_class=JSONResponse)
async def bench_of(thread: str = "") -> JSONResponse:
    """One chat's workbench, for the page to put on the surface when somebody switches to it.

    The page has always cleared the surface on a chat switch and said, correctly, that "the
    workbench belongs to the chat" — it just had nowhere to keep the other chat's one. Now it does,
    so switching is a switch rather than a clear (044-a-bench-per-chat.sql).
    """
    return JSONResponse(
        {
            "cards": [card.model_dump() for card in await store.bench_cards(thread)],
            # What this chat's enquiry is about, so the page can mark it when the surface comes
            # back rather than losing which card everything else hangs from (050).
            "start": await store.began(thread),
        }
    )


@router.post("/workbench/start", response_class=JSONResponse)
async def begin_with(request: Request) -> JSONResponse:
    """Say which card this enquiry starts from.

    Named rather than made: the card already exists on the bench, and a route that made one would
    be a second way of adding a card that has to stay in step with the first.
    """
    form = await _form(request)
    thread = str(form.get("thread", ""))
    name = str(form.get("name", "")).strip()
    if name:
        await store.begin_with(thread, name)
    return JSONResponse({"start": await store.began(thread)})


@router.post("/workbench/arrange", response_class=JSONResponse)
async def arrange_the_enquiry(request: Request) -> JSONResponse:
    """Lay a bench out by following the lines rather than by what each card is.

    The page sends what is on the surface, because it is the only thing that knows — including how
    tall each card has drawn itself, which nothing on this side can work out and a layout computed
    against a guessed height overlaps the moment a card says two lines instead of one. The lines go
    the same way for the same reason: half of them are the page's own (an answer joined to its
    question, a question to what it follows on from) and were never written down.

    A body that will not parse lays nothing out, which is the surface somebody already has.
    """
    try:
        said = await request.json()
        cards = [
            branching.Card(
                name=str(one["name"]), width=int(one["width"]), height=int(one["height"])
            )
            for one in said.get("cards", [])
        ]
        lines = [dict(one) for one in said.get("lines", [])]
    except (TypeError, ValueError, KeyError):
        return JSONResponse({"spots": {}})
    return JSONResponse(
        {
            "spots": {
                name: {"x": at.x, "y": at.y} for name, at in branching.lay_out(cards, lines).items()
            }
        }
    )


@router.post("/workbench/undo", response_class=JSONResponse)
async def undo_bench(request: Request) -> JSONResponse:
    """Put the workbench back the way it was before the last thing that changed it.

    The restored surface comes back with the answer rather than being fetched afterwards, because
    between the two the page would still be holding the state it just undid — and its next write
    would put that state back. Undoing has to hand the page what to draw.

    `undone: false` is a real answer, not an error: there is nothing to go back to, and the page
    says so. A press that quietly does nothing is the one outcome a control like this cannot have,
    because its whole job is to make somebody confident that trying things is safe.
    """
    thread = str((await _form(request)).get("thread", ""))
    undone = await store.undo_bench(thread)
    return JSONResponse(
        {
            "undone": undone,
            "cards": [card.model_dump() for card in await store.bench_cards(thread)],
        }
    )


async def _bench_cards(names: Sequence[str]) -> list[process.Card]:
    """The cards on somebody's bench, as the process reader needs them.

    The names come from the page rather than from `store.bench_cards()`, and that is not an
    oversight: the page asks this while somebody is still arranging, before the surface has been
    written down, and a reading of a bench that lags a drag by a second is a reading of a bench
    nobody is looking at.
    """
    chosen = await store.card_roles()
    said = await store.card_fields()
    made = await store.cards_made()
    labels = {f"idea:{one.id}": one.summary for one in await store.ideas(limit=400)}
    labels |= {one.name: one.label for one in await store.step_cards()}
    cards = []
    for name in names:
        kind = name.split(":", 1)[0]
        cards.append(
            process.Card(
                name=name,
                role=roles.role_of(kind, chosen.get(name, "")).name,
                label=labels.get(name, name),
                said=said.get(name, {}),
                made=made.get(name, ""),
            )
        )
    return cards


@router.get("/workbench/process", response_class=JSONResponse)
async def workbench_process(cards: str = "") -> JSONResponse:
    """Read the bench as a process: the order, what is missing, and what each step would be told.

    Everything here comes out of `agent_desk/process.py`, which is pure — so what this answers and
    what a run would actually do cannot drift apart. That is the same argument as
    `autostart.why_not`: a console that says one thing and does another is worse than one that
    says nothing.
    """
    names = [one for one in cards.split(",") if one]
    on_bench = await _bench_cards(names)
    here = set(names)
    lines = [
        process.Line(from_name=tie.from_name, to_name=tie.to_name, kind=tie.kind, says=tie.says)
        for tie in await store.card_ties()
        if tie.from_name in here and tie.to_name in here
    ]
    walked = process.order(on_bench, lines)
    leaves = await store.card_leaves()
    return JSONResponse(
        {
            "order": list(walked.steps),
            "tangled": list(walked.tangled),
            "why_not": process.ready_to_run(on_bench, lines),
            "unfinished": {name: list(gaps) for name, gaps in process.unfinished(on_bench).items()},
            # The whole thing walked through without running any of it: the order, what each step
            # would be told, the ways out of every Decision, and where it would stop. Nothing new
            # is computed — this is `order`, `memory_for` and `roles.missing` put side by side in
            # the sequence they would happen in (01M1XED1C0SDGWHMX3GRYBE47R).
            "walk": [
                {
                    "name": one.name,
                    "label": one.label,
                    "role": one.role,
                    "told": one.told,
                    "branches": list(one.branches),
                    "stops": one.stops,
                }
                for one in process.walk(on_bench, lines)
            ],
            # What each step would be told about what leads into it. Computed here rather than
            # when a run starts, so that "what does this step actually get" is a question somebody
            # can answer by looking, before anything costs anything.
            "memory": {
                card.name: process.memory_for(card.name, on_bench, lines)
                for card in on_bench
                if card.role in process.STEPS
            },
            # What each step may do, as the engine will read it — not as the switches stand. A
            # step whose work is a prompt may only read, and it is the same one function that
            # decides here and there, so the page cannot show a permission the run will not use.
            "leave": {
                card.name: list(
                    allowed.leave_for_a_prompt()
                    if allowed.is_a_prompt(card.said)
                    else allowed.leave_for(leaves.get(card.name))
                )
                for card in on_bench
                if card.role in process.STEPS
            },
            # And which of those cannot be changed. A switch that can be moved and then ignored is
            # worse than no switch: it is a promise the console does not keep
            # (01M1X8DA8XDSQ16N5DVDVZGM5X).
            "fixed": [
                card.name
                for card in on_bench
                if card.role in process.STEPS and allowed.is_a_prompt(card.said)
            ],
            "allowed": {
                name: {
                    "says": one.says,
                    "means": one.means,
                    "held": one.held,
                    "how": one.how,
                }
                for name, one in allowed.ALLOWED.items()
            },
        }
    )


@router.post("/workbench/run", response_class=JSONResponse)
async def start_run(request: Request) -> JSONResponse:
    """Run the drawing on somebody's workbench (agent_desk/web/engine.py).

    The refusal comes from the same function the panel shows, so a button that is offered and a
    run that is refused cannot disagree about why.
    """
    form = await _form(request)
    names = [one for one in form.get("cards", "").split(",") if one]
    # "В схеме может быть несколько независимых веток, и запускать хочется ту, над которой сейчас
    # думаешь, а не всё сразу." `from` names the card somebody pressed, and what runs is that card
    # and everything downstream of it — worked out here rather than on the page, because the order
    # a branch runs in is `process.order`'s answer and a second one would be a second answer.
    start = str(form.get("from", "")).strip()
    if start:
        on_bench = await _bench_cards(names)
        here = set(names)
        lines = [
            process.Line(from_name=tie.from_name, to_name=tie.to_name, kind=tie.kind, says=tie.says)
            for tie in await store.card_ties()
            if tie.from_name in here and tie.to_name in here
        ]
        names = list(process.from_here(start, on_bench, lines))
        if not names:
            return JSONResponse(
                {"started": False, "why": "that card is not on the workbench"}, status_code=409
            )
    where = await _where_for(names)
    made, why = await engine.begin(
        store, names=names, repo_key=where[0], cwd=where[1], given=str(form.get("given", ""))
    )
    if made is None:
        return JSONResponse({"started": False, "why": why}, status_code=409)
    return JSONResponse({"started": True, "run": made.id})


async def _where_for(names: Sequence[str]) -> tuple[str, str]:
    """Which project a run happens in: the one the cards are about.

    Read from the ideas on the bench, because that is the only card kind that carries a project a
    person chose. A drawing whose cards are about nothing in particular has nowhere to run, and
    `engine.begin` says so rather than picking a project.
    """
    ideas = {f"idea:{one.id}": one for one in await store.ideas(limit=400)}
    keys = [ideas[name].project_key for name in names if name in ideas and ideas[name].project_key]
    if not keys:
        return ("", "")
    rows = await asyncio.to_thread(sessions_only)
    named = next((one for one in shape(rows, await store.groups()) if one.key == keys[0]), None)
    if named is None or not named.instances:
        return (keys[0] or "", "")
    return (named.key, named.instances[0].path)


@router.post("/workbench/happened", response_class=JSONResponse)
async def event_happened(request: Request) -> JSONResponse:
    """Somebody says the thing an Event step was waiting for has happened.

    A human act, and it has to be: whether the release went out is not something this console can
    read, and guessing would start the rest of a process on the strength of nothing.
    """
    form = await _form(request)
    run_id = form.get("run", "").strip()
    name = form.get("name", "").strip()
    if run_id and name:
        await engine.it_happened(store, run_id, name)
    return JSONResponse({"noted": True})


@router.post("/workbench/stop", response_class=JSONResponse)
async def stop_run(request: Request) -> JSONResponse:
    """Stop a run. It keeps its reason: "it ended" and "somebody stopped it at step three" are
    different things to come back to."""
    form = await _form(request)
    run_id = form.get("run", "").strip()
    if run_id:
        await store.end_run(run_id, why="stopped here")
    return JSONResponse({"stopped": True})


@router.post("/workbench/pause", response_class=JSONResponse)
async def pause_run(request: Request) -> JSONResponse:
    """Set a run aside without ending it (047-a-run-can-wait.sql).

    "Между ними нет «пока не надо» — а именно оно нужно, когда упёрлись в лимит или ждут человека."
    """
    run_id = (await _form(request)).get("run", "").strip()
    if run_id:
        await store.pause_run(run_id)
    return JSONResponse({"paused": True})


@router.post("/workbench/carry-on", response_class=JSONResponse)
async def carry_on_run(request: Request) -> JSONResponse:
    """Start a run going again — after a pause, or after a step failed and was fixed.

    One route for both because they are one act: whatever it was waiting for has been dealt with.
    A run that reached its end is not restarted by this; it is over, and starting it again is
    running the drawing, which is a different button.
    """
    run_id = (await _form(request)).get("run", "").strip()
    if run_id:
        await store.carry_on_run(run_id)
    return JSONResponse({"going": True})


@router.get("/workbench/runs", response_class=JSONResponse)
async def workbench_runs() -> JSONResponse:
    """Every run and where it got to, so the bench can show it on the cards themselves."""
    found = []
    for one in await store.runs():
        found.append(
            {
                "id": one.id,
                "cards": one.names,
                "at": one.at,
                "going": one.going,
                # Set aside, as opposed to over. The page offers different things for the two, and
                # telling them apart from `going` alone is impossible (047-a-run-can-wait.sql).
                "waiting": one.waiting,
                "canCarryOn": one.waiting or bool(one.stopped_why),
                "why": one.stopped_why or "",
                "steps": [
                    {
                        "name": step.name,
                        "state": step.state,
                        "made": step.made,
                        "detail": step.detail,
                        # What it cost and how long it took, so the answer to "is this prompt
                        # worth it" is beside the answer rather than in a bill (058).
                        "usd": step.usd,
                        "ms": step.ms,
                    }
                    for step in await store.run_steps(one.id)
                ],
            }
        )
    return JSONResponse({"runs": found})


# How many times one drawing may be started at once. A spread needs a handful, not a hundred: ten
# runs of a five-step pipeline is fifty model calls, which is a number somebody should be able to
# picture before pressing (01M1XA1V9T96HECGYPGVGJ230Q).
MOST_TIMES = 10


@router.post("/workbench/repeat", response_class=JSONResponse)
async def repeat_a_run(request: Request) -> JSONResponse:
    """Run this drawing several times — the same input over, or one run per line of a set.

    "Модель отвечает по-разному… решение по одной выдаче — это решение по шуму." And the same
    machinery from the other end: one run per example is how "поиграться" becomes "померить".

    Only a drawing made entirely of prompts. Ten runs of a drawing with work in it is ten agents in
    ten worktrees, which is not a thing to start from a text box — and a harness is prompts by
    definition, so nothing that this is for is refused (agent_desk/spread.py).
    """
    form = await _form(request)
    names = [one for one in form.get("cards", "").split(",") if one]
    on_bench = await _bench_cards(names)
    if not engine.all_prompts(on_bench):
        return JSONResponse(
            {
                "started": 0,
                "why": "this drawing does work in a checkout, so it is run once and on purpose",
            },
            status_code=409,
        )
    # Either N of the same, or one per line. One list, so the two ideas are one mechanism.
    lines = [one.strip() for one in str(form.get("each", "")).splitlines() if one.strip()]
    given = str(form.get("given", ""))
    wanted = lines or [given] * max(1, min(int(str(form.get("times", "1")) or 1), MOST_TIMES))
    wanted = wanted[:MOST_TIMES]
    made: list[str] = []
    for one in wanted:
        run, why = await engine.begin(store, names=names, repo_key="", cwd="", given=one)
        if run is None:
            return JSONResponse({"started": len(made), "why": why}, status_code=409)
        made.append(run.id)
    return JSONResponse({"started": len(made), "runs": made})


@router.get("/workbench/spread", response_class=JSONResponse)
async def spread_of_runs(cards: str = "") -> JSONResponse:
    """What every run of this drawing produced, step by step (agent_desk/spread.py)."""
    here = {one for one in cards.split(",") if one}
    mine = [one for one in await store.runs() if here & set(one.names)]
    labels = {one.name: one.label for one in await store.step_cards()}
    found = spread.over([await store.run_steps(one.id) for one in mine], labels)
    return JSONResponse(
        {
            "said": found.said,
            "rows": [
                {
                    "name": step.name,
                    "label": step.label,
                    "says": step.says,
                    "changed": len(step.answers) > 1 or bool(step.failed),
                    "before": step.answers[0][0] if step.answers else "",
                    "after": step.answers[1][0] if len(step.answers) > 1 else "",
                    "marks": [],
                }
                for step in found.steps
            ],
        }
    )


@router.get("/workbench/compare", response_class=JSONResponse)
async def compare_two_runs(runs: str = "") -> JSONResponse:
    """Two runs of one drawing, step by step (agent_desk/comparing.py).

    Named by id rather than "the last two", because which two is a thing the person is looking at
    and the newest run is not always the interesting one.
    """
    wanted = [one for one in runs.split(",") if one][:2]
    if len(wanted) != 2:
        return JSONResponse({"rows": [], "said": "two runs are needed to compare two runs"})
    earlier, later = (await store.run_steps(wanted[0]), await store.run_steps(wanted[1]))
    labels = {one.name: one.label for one in await store.step_cards()}
    rows = comparing.against(earlier, later, labels)
    return JSONResponse(
        {
            "said": comparing.in_a_word(rows),
            "rows": [
                {
                    "name": row.name,
                    "label": row.label,
                    "before": row.before,
                    "after": row.after,
                    "says": row.says,
                    "changed": row.changed,
                    # Word by word, with what changed marked. Two answers side by side are
                    # readable; two with the changed words marked are comparable, which is the
                    # thing the harness is assembled to reach.
                    "marks": [{"mark": mark, "text": text} for mark, text in row.marks],
                }
                for row in rows
            ],
        }
    )


# Under `/workbench` for the reason `/workbench/why` is: `/cards/{kind}` is registered earlier and
# matches `/cards/answers` with kind="answers", so this answered 404 to every request from the day
# it was written. The control on the card did nothing and said nothing, and no test saw it because
# every one of them called the function.
@router.get("/workbench/answers", response_class=JSONResponse)
async def answers_on_a_card(name: str = "") -> JSONResponse:
    """The several answers one card produced, side by side (01M1XA1V906B3KRJ84G4KHRE33).

    "Два ответа, показанные друг под другом с отличиями — это то, ради чего собирают такую схему."

    The same rows and the same panel as two runs compared, because it is the same question asked of
    different things: here are two texts, what is different about them. A second panel would be a
    second answer to "how is a difference shown", and they would drift.
    """
    made = (await store.cards_made()).get(name, "")
    answers = engine.read_a_fan(made)
    if len(answers) < 2:
        return JSONResponse({"rows": [], "said": "that card produced one answer, not several"})
    # Every answer against the first, which is the reading a fan invites: one model is the one you
    # had, and the others are what the rest said instead.
    first = answers[0]
    rows = [
        comparing.Row(name=other, label=f"{first[0]} → {other}", before=first[1], after=said)
        for other, said in answers[1:]
    ]
    return JSONResponse(
        {
            "said": comparing.in_a_word(rows),
            "rows": [
                {
                    "name": row.name,
                    "label": row.label,
                    "before": row.before,
                    "after": row.after,
                    "says": row.says,
                    "changed": row.changed,
                    "marks": [{"mark": mark, "text": text} for mark, text in row.marks],
                }
                for row in rows
            ],
        }
    )


# --- tools: a card with behaviour, kept (065-a-tool-you-keep.sql) -------------------------------
# "Уникальная карточка, в которую можно закладывать разнообразный функционал: например заложить туда
# кнопку с промптом… Хранятся в списке под проектами, слева снизу."
#
# A button and a check are the two card kinds that hold behaviour rather than information, and both
# die with the workbench they were made on. Somebody who writes "декомпозируй" as a button writes it
# again in the next chat, and by the fourth chat they stop bothering. A tool is that card, kept.
# Under `/workbench` and not `/cards`, which is where it was first written and where it was
# unreachable: `/cards/{kind}` is registered earlier and matched `/cards/why` with kind="why",
# answering 404 to every request. The unit tests called the function and never went through the
# router, so it looked fine until a browser asked for it.
@router.get("/workbench/file", response_class=JSONResponse)
async def the_whole_workbench(thread: str = "") -> JSONResponse:
    """A whole workbench as one document (agent_desk/carrying.py).

    "Вот всё, над чем я думал" as one thing: attach it to a ticket, put it in a repository beside
    the code, open it in a month. It is also the backup this console does not otherwise have.

    Cards, where they sat and the lines between them — and nothing a card's body holds. A file
    somebody attaches to a ticket is a file somebody else reads, which is the surface
    docs/07-security.md says redacts before it renders; a label is what is already visible on a
    folded card across the room.
    """
    cards = [
        carrying.Card(
            name=one.name,
            kind=one.kind,
            label=one.label,
            x=one.x,
            y=one.y,
            shown=one.shown,
            spent=one.spent,
            came=one.came,
        )
        for one in await store.bench_cards(thread)
    ]
    on_it = {one.name for one in cards}
    lines = [
        carrying.Line(from_name=tie.from_name, to_name=tie.to_name, kind=tie.kind, says=tie.says)
        for tie in await store.card_ties()
        if tie.from_name in on_it and tie.to_name in on_it
    ]
    thread_row = await store.thread(thread) if thread else None
    return JSONResponse(
        carrying.as_document(cards, lines, name=thread_row.subject if thread_row else "")
    )


@router.post("/workbench/file", response_class=JSONResponse)
async def open_a_workbench(request: Request) -> JSONResponse:
    """Put a document's cards and lines onto this chat's workbench.

    Everything the document carries whose row is on this machine, and a count of what it does not
    have. A bench that quietly came back with eleven of fourteen cards would be the fifth rule in a
    file format, so the number is the answer rather than a detail.
    """
    said = await request.json()
    bench = carrying.read_document(said)
    if bench is None:
        return JSONResponse(
            {"why": "That is not a workbench this console can open."}, status_code=422
        )
    thread = str((said or {}).get("into", "")) if isinstance(said, dict) else ""
    here: list[BenchCard] = []
    missing: list[str] = []
    for at, one in enumerate(bench.cards):
        if not await _card_is_here(one.name):
            missing.append(one.name)
            continue
        here.append(
            BenchCard(
                name=one.name,
                kind=one.kind,
                card_id=one.name.partition(":")[2],
                label=one.label,
                x=one.x,
                y=one.y,
                shown=one.shown,
                spent=one.spent,
                ord=at,
                by_hand=True,
                came="opened from a file",
            )
        )
    await store.keep_bench(here, thread_id=thread)
    on_it = {one.name for one in here}
    for line in bench.lines:
        if line.from_name in on_it and line.to_name in on_it:
            await store.tie_cards(
                from_name=line.from_name,
                to_name=line.to_name,
                kind=line.kind,
                says=line.says,
                thread_id=thread,
            )
    return JSONResponse({"opened": len(here), "missing": missing})


async def _card_is_here(name: str) -> bool:
    """Whether the thing a document names still exists on this machine.

    Only for the kinds this console owns rows for. A session or a folder is named by what it is
    rather than by a row, so it comes back as it was named and the machine decides whether it is
    there — which is what the board already does for every other card of those kinds.
    """
    kind, _, ident = name.partition(":")
    if kind == "idea":
        return await store.idea(ident) is not None
    if kind in ("block", "answer"):
        return await store.block(ident) is not None
    if kind == "button":
        return await store.button_card(ident) is not None
    if kind == "check":
        return await store.check_card(ident) is not None
    return True


@router.get("/workbench/why", response_class=JSONResponse)
async def why_it_is_here(name: str = "", thread: str = "") -> JSONResponse:
    """The chain of facts behind one card (agent_desk/because.py).

    "На любое утверждение уметь показать, из чего оно следует." Every step here was already worked
    out and thrown away — `came` when the card arrived, `relates_to` when the question was read,
    `made_from` when two cards were dragged together. Nothing is computed and nothing is asked of a
    model: this reads rows and turns them into sentences, each carrying the column it came from.

    An empty chain is an answer. A card nobody can say anything about gets no steps rather than an
    invented reason, which is the fifth rule in the one place it is easiest to break.
    """
    kind, _, ident = name.partition(":")
    steps: list[because.Step] = []
    if kind == "idea":
        idea = await store.idea(ident)
        if idea is not None:
            block = await store.block(idea.block_id) if idea.block_id else None
            parent = await store.idea(idea.parent_id) if idea.parent_id else None
            filed = await store.filing_of(idea.id)
            steps += because.about_an_idea(
                summary=idea.summary or idea.text,
                source_kind=idea.source_kind,
                parent=(parent.summary or parent.text) if parent else "",
                asked=block.input if block else "",
                state=idea.state,
                filed=f"{filed.tracker} {filed.issue_key}" if filed else "",
            )
    elif kind in ("answer", "block"):
        block = await store.block(ident)
        if block is not None:
            if kind == "answer":
                steps += because.about_an_answer(
                    asked=block.input,
                    made_from=tuple(one for one in block.made_from.split(",") if one),
                    by_button=block.by_button,
                )
            else:
                steps += because.about_a_question(
                    kind=block.kind,
                    relates_to=tuple(one for one in block.relates_to.split(",") if one),
                )
    # And how it got in front of somebody, which is true of every kind and is the line people
    # actually want when they ask "why is this here".
    for card in await store.bench_cards(thread):
        if card.name == name and card.came:
            steps += because.on_the_bench(card.came)
    return JSONResponse({"steps": [{"said": one.said, "from": one.from_} for one in steps]})


@router.post("/tools", response_class=JSONResponse)
async def keep_a_tool(request: Request) -> JSONResponse:
    """Keep a card's behaviour under a name, from the card itself.

    Read off the card rather than typed again: a tool whose prompt is a second copy of the button's
    is a tool that quietly stops matching the thing it was saved from.
    """
    form = await _form(request)
    kind, _, ident = form.get("card", "").strip().partition(":")
    name = form.get("name", "").strip()
    if kind == "button":
        card = await store.button_card(ident)
        said = card.prompt if card else None
    elif kind == "check":
        checked = await store.check_card(ident)
        said = checked.said if checked else None
    else:
        return JSONResponse({"why": "Only a button or a check can be kept as a tool."})
    if said is None:
        return JSONResponse({"why": "That card is not here any more."})
    made = await store.keep_tool(name=name, kind=kind, said=said)
    if made is None:
        return JSONResponse({"why": "A tool needs a name."})
    return JSONResponse({"name": made.name, "kind": made.kind})


@router.get("/tools", response_class=JSONResponse)
async def list_tools() -> JSONResponse:
    return JSONResponse(
        {
            "tools": [
                {"name": one.name, "kind": one.kind, "said": one.said[:120]}
                for one in await store.tools()
            ]
        }
    )


@router.post("/tools/use", response_class=JSONResponse)
async def use_a_tool(request: Request) -> JSONResponse:
    """Make a fresh card from a kept tool.

    A new card every time, which is why the same tool can be on four workbenches at once with four
    different sets of lines — and why editing the card on one bench does not reach the others or
    the tool. The same argument a saved drawing is made under (038).
    """
    form = await _form(request)
    tool = await store.tool(form.get("name", "").strip())
    if tool is None:
        return JSONResponse({"why": "There is no tool by that name."})
    if tool.kind == "button":
        made = await store.add_button_card(tool.name, tool.said)
        return JSONResponse({"kind": "button", "id": made.id, "label": made.label})
    checked = await store.add_check_card(tool.name, tool.said)
    return JSONResponse({"kind": "check", "id": checked.id, "label": checked.label})


@router.post("/tools/describe", response_class=JSONResponse)
async def make_a_tool_from_a_description(request: Request) -> JSONResponse:
    """Make a card from a sentence about what it should do (agent_desk/tooling.py).

    It is made and not kept. Making a card is cheap and undoable — one press takes it off — so it
    happens on the asking; keeping it is a decision about a list that outlives every chat, and that
    stays the separate act it already is.
    """
    form = await _form(request)
    said = form.get("said", "").strip()
    if not said:
        return JSONResponse({"why": "Say what the tool should do."})
    try:
        reply = "".join(
            [chunk async for chunk in answer_session.stream_answer(tooling.what_to_make(said))]
        )
    except (answer_session.AnswerFailed, OSError) as gone:
        return JSONResponse({"why": f"It could not be made: {str(gone)[:120]}"})
    made = tooling.read_made(reply)
    if made is None:
        return JSONResponse(
            {
                "why": "That is not a button or a check, which are the two kinds of tool this "
                "console can make."
            }
        )
    if made.kind == "button":
        card = await store.add_button_card(made.name, made.said)
        return JSONResponse({"kind": "button", "id": card.id, "label": card.label})
    checked = await store.add_check_card(made.name, made.said)
    return JSONResponse({"kind": "check", "id": checked.id, "label": checked.label})


@router.post("/tools/drop", response_class=JSONResponse)
async def forget_a_tool(request: Request) -> JSONResponse:
    """Forget one. The cards it already made stay: they are copies, and a card that vanished
    because somebody tidied a list is a workbench that changed while nobody was looking."""
    form = await _form(request)
    await store.forget_tool(form.get("name", "").strip())
    return JSONResponse({"forgot": True})


@router.post("/cards/check", response_class=JSONResponse)
async def add_check_card(request: Request) -> JSONResponse:
    """A new check, with a name and what the answer has to be (062)."""
    form = await _form(request)
    made = await store.add_check_card(
        form.get("label", "").strip() or "a check", form.get("said", "").strip()
    )
    return JSONResponse({"id": made.id, "name": made.name, "label": made.label})


@router.post("/cards/check/edit", response_class=HTMLResponse)
async def edit_check_card(request: Request) -> Response:
    """What it is called and what it checks. The verdict goes with the edit: a card saying "passed"
    under a condition somebody has just changed is a card answering a question nobody asked."""
    form = await _form(request)
    card_id = form.get("id", "").strip()
    if card_id:
        await store.set_check_card(
            card_id,
            label=form.get("label", "").strip() or "a check",
            said=form.get("said", ""),
        )
    return HTMLResponse("", status_code=204)


async def _decide(said: str, asked: str, got: str) -> tuple[bool, str, bool] | str:
    """Whether this answer is what it had to be — mechanically if that is possible, else asked.

    Returns `(passed, why, judged)`, or a sentence saying why nothing was decided. Nothing decided
    is not a failure: a model that answered something else has not made a judgement, and writing
    that down as "it did not pass" is a verdict invented from silence.
    """
    mechanical = checking.read(said)
    if mechanical is not None:
        passed, why = checking.passes(mechanical, got)
        return passed, why, False
    try:
        reply = "".join(
            [
                chunk
                async for chunk in answer_session.stream_answer(
                    checking.judgement_prompt(asked, got, said)
                )
            ]
        )
    except (answer_session.AnswerFailed, OSError) as gone:
        return f"it could not be checked: {str(gone)[:120]}"
    verdict = checking.read_verdict(reply)
    if verdict is None:
        return "it did not come back with yes or no, so nothing was decided"
    return verdict[0], verdict[1], True


@router.post("/cards/check/note", response_class=HTMLResponse)
async def note_on_a_check(request: Request) -> Response:
    """What a person says about the verdict, which goes into the next attempt (064).

    Its own route rather than part of the condition edit: changing the condition clears every
    verdict, and a comment about the verdict that stands has to survive the thing it comments on.
    """
    form = await _form(request)
    card_id = form.get("id", "").strip()
    if card_id:
        await store.note_on_a_check(card_id, form.get("note", ""))
    return HTMLResponse("", status_code=204)


@router.post("/workbench/check", response_class=JSONResponse)
async def run_a_check(request: Request) -> JSONResponse:
    """Press a check card: read what it is joined to, and say one of two things about it.

    The two inputs are one card. An answer card already carries both halves of its exchange — what
    was asked is the block's input and what came back is its answer — so a check joined to one
    answer card has everything it needs, and no second kind of wire had to be invented.
    """
    form = await _form(request)
    card = await store.check_card(form.get("id", "").strip())
    if card is None:
        return JSONResponse({"why": "that check is not here any more"}, status_code=404)
    if not card.said.strip():
        return JSONResponse(
            {"why": "That check has nothing to check for yet. Write it on the card."}
        )
    on = [one for one in form.get("on", "").split(",") if one.startswith("answer:")]
    if not on:
        return JSONResponse({"why": "Join it to an answer — a check needs something to check."})
    # The newest, and the card says which. Refusing to choose was the first answer to "joined to
    # two" and using it showed why that is wrong: an answer grown from a check arrives joined to
    # that check, so two is the *ordinary* state after one "try again" — and the line to it is
    # worked out rather than drawn, so it cannot be rubbed out. The fault the refusal was written
    # for was reading one of several *silently*; reading the newest and saying so fixes that too.
    #
    # Newest by id, which is a ULID: lexicographic order is creation order, and no clock is asked.
    reading = max(on)
    block = await store.block(reading.removeprefix("answer:"))
    if block is None or not (block.answer or "").strip():
        return JSONResponse({"why": "That answer has nothing in it yet."})
    decided = await _decide(card.said, block.input, block.answer or "")
    if isinstance(decided, str):
        return JSONResponse({"why": decided})
    passed, why, judged = decided
    await store.card_checked(card.id, passed=passed, why=why, judged=judged, about=reading)
    return JSONResponse(
        {
            "verdict": "passed" if passed else "failed",
            "why": why,
            "judged": judged,
            "about": reading,
        }
    )


@router.post("/cards/button", response_class=JSONResponse)
async def add_button_card(request: Request) -> JSONResponse:
    """A new button, with a name and the request it sends (059)."""
    form = await _form(request)
    made = await store.add_button_card(
        form.get("label", "").strip() or "a button", form.get("prompt", "").strip()
    )
    return JSONResponse({"id": made.id, "name": made.name, "label": made.label})


@router.post("/cards/button/edit", response_class=HTMLResponse)
async def edit_button_card(request: Request) -> Response:
    """What it is called and what it asks. One edit: a button renamed while its request still says
    something else is how a bench fills with controls nobody dares press."""
    form = await _form(request)
    card_id = form.get("id", "").strip()
    if card_id:
        await store.set_button_card(
            card_id,
            label=form.get("label", "").strip() or "a button",
            prompt=form.get("prompt", ""),
        )
    return HTMLResponse("", status_code=204)


@router.post("/cards/step", response_class=JSONResponse)
async def add_step_card(request: Request) -> JSONResponse:
    """A card that is only a card (038-steps-and-templates.sql).

    Everything else on the workbench stands for something that already exists. This is the one you
    draw before the thing exists, which is what describing a process requires.
    """
    form = await _form(request)
    made = await store.add_step_card(form.get("label", "").strip() or "a step")
    if form.get("role", "") and roles.is_a_role(form["role"]):
        await store.set_card_role(made.name, form["role"])
    return JSONResponse({"id": made.id, "name": made.name, "label": made.label})


@router.post("/cards/step/name", response_class=HTMLResponse)
async def name_step_card(request: Request) -> Response:
    """What to call a step. The one thing a step card holds that is its own."""
    form = await _form(request)
    card_id = form.get("id", "").strip()
    label = form.get("label", "").strip()
    if card_id and label:
        await store.name_step_card(card_id, label)
    return HTMLResponse("", status_code=204)


@router.post("/workbench/template", response_class=JSONResponse)
async def keep_template(request: Request) -> JSONResponse:
    """Save the drawing on somebody's workbench under a name.

    A shape rather than a copy: the roles, what each step says, what each may do, and the lines —
    with the steps numbered, because the cards a template makes are new cards and cannot be the
    ones it was saved from.
    """
    form = await _form(request)
    name = form.get("name", "").strip()
    names = [one for one in form.get("cards", "").split(",") if one]
    if not name or not names:
        return JSONResponse({"kept": False, "why": "it needs a name and some cards"}, 400)
    cards = await _bench_cards(names)
    here = {one: number for number, one in enumerate(names, start=1)}
    leaves = await store.card_leaves()
    # Where each card sat, measured from the top-left of the saved set rather than from the bench
    # (048-a-template-remembers-where.sql). Offsets, so a template used on a bench that already has
    # cards on it keeps its shape without landing on top of them.
    where = {one.name: one for one in await store.bench_cards(form.get("thread", "").strip())}
    placed = [where[one] for one in names if one in where]
    left = min((one.x for one in placed), default=0)
    top = min((one.y for one in placed), default=0)
    steps = [
        TemplateStep(
            ord=here[card.name],
            role=card.role,
            label=card.label,
            fields=dict(card.said),
            leave=tuple(leaves.get(card.name, ())),
            dx=where[card.name].x - left if card.name in where else None,
            dy=where[card.name].y - top if card.name in where else None,
        )
        for card in cards
    ]
    lines = [
        TemplateLine(
            from_ord=here[tie.from_name],
            to_ord=here[tie.to_name],
            kind=tie.kind,
            says=tie.says,
        )
        for tie in await store.card_ties()
        if tie.from_name in here and tie.to_name in here
    ]
    await store.keep_template(name=name, steps=steps, lines=lines)
    return JSONResponse({"kept": True, "steps": len(steps), "lines": len(lines)})


@router.get("/workbench/templates", response_class=JSONResponse)
async def list_templates() -> JSONResponse:
    return JSONResponse(
        {
            "templates": [
                {"name": one.name, "steps": len(one.steps), "lines": len(one.lines)}
                for one in await store.templates()
            ]
        }
    )


@router.post("/workbench/template/use", response_class=JSONResponse)
async def use_template(request: Request) -> JSONResponse:
    """Make a fresh set of cards in the shape of a saved drawing.

    New cards every time, which is the whole point: *"процесс, который собрали один раз, должен
    запускаться второй раз с другими входами"*. A template that put the same cards back would be
    a bookmark rather than a template — the second run would overwrite what the first produced.
    """
    form = await _form(request)
    name = form.get("name", "").strip()
    made = next((one for one in await store.templates() if one.name == name), None)
    if made is None:
        return JSONResponse({"made": False, "why": "there is no template by that name"}, 404)
    fresh: dict[int, str] = {}
    # Fields the template carries that its role no longer asks for. Dropping them is right and was
    # already happening; not saying so was the hole. "Поля, которых у роли больше нет, сейчас молча
    # не записываются — это правильно, но человек об этом не узнаёт и получает карточку, которая
    # выглядит заполненной."
    #
    # Counted by field name rather than per card, because a template of nine steps that all lost
    # the same field has lost one thing nine times, and "nine fields are gone" reads as nine
    # different problems.
    lost: set[str] = set()
    for step in made.steps:
        card = await store.add_step_card(step.label)
        fresh[step.ord] = card.name
        await store.set_card_role(card.name, step.role)
        for asked, value in step.fields.items():
            # Only what this role actually asks. A template saved before a role learned or lost a
            # field must not write one that no longer exists — a card that looks filled in and
            # reads as empty to everything else.
            if roles.is_a_field(step.role, asked):
                await store.set_card_field(card.name, asked, value)
            elif value.strip():
                # Only when something was actually written in it. A field somebody left empty and
                # a field that has since been removed are the same absence on the new card, and
                # only one of them is worth a sentence.
                lost.add(f"{step.role} · {asked}")
        if step.leave:
            await store.set_card_leave(card.name, list(step.leave))
    for line in made.lines:
        if line.from_ord in fresh and line.to_ord in fresh:
            await store.tie_cards(
                from_name=fresh[line.from_ord],
                to_name=fresh[line.to_ord],
                kind=line.kind,
                says=line.says,
            )
    return JSONResponse(
        {
            "made": True,
            # Each card with where it sat in the drawing, when the template remembers. A template
            # saved before 048 says nothing, and the page lays those out the way it always did.
            "cards": [
                {"name": fresh[step.ord], "dx": step.dx, "dy": step.dy}
                for step in made.steps
                if step.ord in fresh
            ],
            "lost": sorted(lost),
        }
    )


@router.post("/workbench/template/drop", response_class=JSONResponse)
async def drop_template(request: Request) -> JSONResponse:
    form = await _form(request)
    await store.drop_template(form.get("name", "").strip())
    return JSONResponse({"gone": True})


@router.get("/workbench/words", response_class=JSONResponse)
async def workbench_words(cards: str = "") -> JSONResponse:
    """The drawing said in words somebody can read without opening it.

    No model call: the order comes from the lines and the words from the fields, so this has one
    right answer. A description that came back differently on two afternoons would be no use for
    the thing it is for — handing work to somebody who was not in the room.
    """
    names = [one for one in cards.split(",") if one]
    on_bench = await _bench_cards(names)
    here = set(names)
    lines = [
        process.Line(from_name=tie.from_name, to_name=tie.to_name, kind=tie.kind, says=tie.says)
        for tie in await store.card_ties()
        if tie.from_name in here and tie.to_name in here
    ]
    return JSONResponse({"words": telling.as_words(on_bench, lines)})


@router.post("/workbench/sketch", response_class=JSONResponse)
async def sketch_from_words(request: Request) -> JSONResponse:
    """Read a description and *propose* a drawing. Nothing is put on the bench here.

    A guess, so it is offered rather than applied — the same rule the meeting intake and the whole
    idea pool follow: a machine may propose, a person disposes.
    """
    form = await _form(request)
    said = form.get("words", "").strip()
    if not said:
        return JSONResponse({"read": False, "why": "there is nothing to read"}, status_code=400)
    try:
        reply = "".join(
            [chunk async for chunk in answer_session.stream_answer(telling.shape_prompt(said))]
        )
    except (answer_session.AnswerFailed, OSError) as gone:
        return JSONResponse({"read": False, "why": str(gone)[:200]}, status_code=502)
    steps, lines = telling.read_shape(reply)
    if not steps:
        return JSONResponse(
            {"read": False, "why": "it did not come back with a shape this could read"},
            status_code=422,
        )
    return JSONResponse({"read": True, "steps": steps, "lines": lines})


@router.post("/workbench/sketch/keep", response_class=JSONResponse)
async def keep_sketch(request: Request) -> JSONResponse:
    """Put a proposed drawing on the bench, once somebody has said so.

    Split from the proposal deliberately: the model call and the write are two acts, and a person
    presses between them.
    """
    form = await _form(request)
    steps = []
    for raw in form.get("steps", "").split("\n"):
        role, _, rest = raw.partition("|")
        label, _, words = rest.partition("|")
        steps.append({"role": role.strip(), "label": label.strip(), "words": words.strip()})
    lines = []
    for raw in form.get("lines", "").split("\n"):
        bits = raw.split("|")
        if len(bits) < 3 or not bits[0].strip().isdigit() or not bits[1].strip().isdigit():
            continue
        lines.append(
            {
                "from": bits[0].strip(),
                "to": bits[1].strip(),
                "kind": bits[2].strip(),
                "says": bits[3].strip() if len(bits) > 3 else "",
            }
        )
    # The same function the input field's "draw me a process" uses. Two copies of this were two
    # answers to "what does a drawn process become", and the day they differ is the day one
    # description produces two different benches.
    names = await block_runs.cards_from_shape(store, steps, lines)
    return JSONResponse({"made": True, "cards": [{"name": one} for one in names]})


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


@router.post("/ideas/{idea_id}/project", response_class=HTMLResponse)
async def point_idea_at_project(idea_id: str, request: Request) -> Response:
    """Say which project an idea is about, over whatever was worked out for it.

    "Проект определяется автоматически, но при этом пользователь может скорректировать; если это
    блокер или идея — есть выпадающий список с проектами."

    Automatically is a guess — a thought typed with nothing on the workbench is about the thing in
    front of you — and a guess needs a way to be wrong out loud. Blank means "nothing in
    particular", which is a real answer and not an absence.
    """
    form = await _form(request)
    await store.set_idea_project(idea_id, form.get("key", "").strip() or None)
    idea = await store.idea(idea_id)
    return HTMLResponse(
        env.get_template("_card_idea.html").render(
            idea=idea,
            said=await describe_card("idea", idea_id) if idea else "",
            projects=await _project_choices(),
        ),
        status_code=200 if idea else 404,
    )


def sessions_only() -> list[BoardRow]:
    """The board without the reading: every session, and none of their transcripts.

    `board` reads the registry and then opens the tail of every live session, which is where
    almost all of its time goes. `shape` — the thing that folds sessions into projects — never
    looks at a tail or a hint: it groups by working directory and asks git what repository each
    one is. So anything that only wants the list of projects was paying for a file read per
    session to get a field it does not use.

    Measured at 37ms against 15 sessions on this machine, on a path that runs whenever the ideas
    column re-renders. `test_shape_reads_only_the_session` is what keeps this true.
    """
    now = now_ms()
    return [
        BoardRow(
            session=session,
            tail=None,
            hint=attention_hint(session, None, now=now, after_seconds=settings.idle_hint_seconds),
        )
        for session in registry.read_registry().sessions
    ]


async def _project_choices() -> list[tuple[str, str]]:
    """Every project a card could be pointed at, as (key, name)."""
    rows = await asyncio.to_thread(sessions_only)
    return [(one.key, one.name) for one in shape(rows, await store.groups())]


@router.get("/ideas/{idea_id}/kin", response_class=HTMLResponse)
async def idea_kin(idea_id: str) -> HTMLResponse:
    """What an idea is made of and what it belongs to, for the workbench to bring along.

    "При записи идеи сперва отображается карточка идеи, а далее появляются под-идеи (отдельные
    карточки)… если дочерние идеи тоже декомпозированы — ситуация повторяется со сдвигом", and
    "при помещении идеи на верстак рядом с ней появляется связанный проект-карточка".

    A tree, bounded: an idea with forty descendants is a workbench nobody can use.
    """
    ideas = {one.id: one for one in await store.ideas(limit=500)}
    if idea_id not in ideas:
        return HTMLResponse("{}", media_type="application/json", status_code=404)

    children: dict[str, list[str]] = {}
    for one in ideas.values():
        if one.parent_id:
            children.setdefault(one.parent_id, []).append(one.id)

    def tree(of: str, depth: int) -> list[dict[str, object]]:
        if depth > 3:
            return []
        return [
            {
                "id": child,
                "parent": of,
                "summary": ideas[child].summary,
                "children": tree(child, depth + 1),
            }
            for child in children.get(of, [])[:8]
            if child in ideas
        ]

    project = None
    key = ideas[idea_id].project_key
    if key:
        rows, _ = await asyncio.to_thread(board)
        named = next((one for one in shape(rows, await store.groups()) if one.key == key), None)
        project = {"key": key, "name": named.name if named else key.split(":")[-1]}

    return HTMLResponse(
        json.dumps({"project": project, "children": tree(idea_id, 1)}),
        media_type="application/json",
    )


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


@router.post("/ideas/from-bench", response_class=JSONResponse)
async def idea_from_bench(request: Request) -> JSONResponse:
    """Make an idea out of what is on the workbench, and mark it as the person's own.

    "Я перетягиваю твою идею на верстак, начинаю задавать тебе вопросы, уточнения… в финале я
    должен получить блок, в котором будет кнопка «добавить как идею» — при нажатии собираем
    контекст из полученных карточек и формируем идею, помеченную как обычную, то есть мою."

    `human` is not a claim about who typed it. It means somebody now holds the context this idea
    grew out of — which, after a conversation they drove, they do. That is exactly what the column
    distinguishes (039-idea-author.sql), so marking it here is the honest answer rather than a
    convenient one.

    What goes in is what the cards say: their names and, where a card has said what it is, that
    sentence. Not the whole transcript — an idea that arrives as a wall of conversation is an idea
    nobody reads twice.
    """
    form = await _form(request)
    names = [one for one in form.get("cards", "").split(",") if one]
    summary = form.get("summary", "").strip()
    if not names and not summary:
        return JSONResponse({"made": False, "why": "there is nothing to make one from"}, 400)

    cards = await _bench_cards(names)
    said = [summary] if summary else []
    for card in cards:
        line = card.label or card.name
        words = next(
            (
                (card.said.get(field.name) or "").strip()
                for field in roles.fields_of(card.role)
                if (card.said.get(field.name) or "").strip()
            ),
            "",
        )
        said.append(f"- {line}{f': {words}' if words else ''}")
        if card.made.strip():
            said.append(f"  what came of it: {card.made.strip()}")

    made = await inbox.capture(
        store,
        "\n".join(said),
        source_kind="typed",
        context={"from": "a conversation on the workbench", "cards": str(len(cards))},
        project_key=(cards[0].name.split(":")[0] and await store.setting(FOCUS_KEY)) or None,
        author="human",
    )
    if summary:
        await store.set_idea_summary(made.id, summary[:120])
    return JSONResponse({"made": True, "id": made.id, "cards": len(cards)})


@router.post("/ideas/aside", response_class=HTMLResponse)
async def show_set_aside(request: Request) -> Response:
    """Show what was set aside, or go back to what is live.

    Setting a proposal aside makes it `dropped`, so this is a filter over a state that already
    exists — and the way back to something dismissed by accident, which a list with no way back is
    a list nobody dismisses anything from.
    """
    form = await _form(request)
    await store.set_setting(ASIDE_KEY, "yes" if form.get("aside") == "yes" else "")
    if _wants_fragment(request):
        return HTMLResponse(await render_ideas())
    return RedirectResponse("/", status_code=303)


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
                await _start_it(claimed)
    elif action == "drop":
        await store.drop_task(task_id)
    elif action == "land":
        # Offer the branch to the project again, once somebody has pushed a fix to it. The same
        # call the settling pass makes, with the same rule behind it: nothing lands that the
        # project's own gate will not take (docs/adr/0008). A gate that says no again leaves the
        # branch exactly where it is and says why, which is what it did the first time.
        task = next((t for t in await store.tasks() if t.id == task_id), None)
        if task is not None and task.finished_at is not None:
            offered = await asyncio.to_thread(land.land, task.cwd, autostart.worktree_of(task))
            await store.task_landed(task.id, offered.detail, landed=offered.landed)
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


@router.post("/blocks/{block_id}/run", response_class=HTMLResponse)
async def run_what_was_understood(block_id: str, request: Request) -> Response:
    """Start the run a message asked for, now that somebody has pressed it.

    The press is the whole point: the drawing puts agents in worktrees, and that is not something
    to be started by a sentence the console had to interpret (01M1Z9ZZTR1MBEXBWZNXMQCHJ7).

    The cards are the ones the block named, not what is on the bench now. Between the asking and
    the pressing somebody may have dragged one off, and running a different drawing from the one
    that was shown would make the showing worthless.
    """
    block = await store.block(block_id)
    said, names = telling.read_will_run(block.answer or "") if block else ("", [])
    if block is None or block.kind != "running" or not names:
        return HTMLResponse(_a_sentence("There is nothing waiting to be run there."), 404)
    where = await _where_for(names)
    made, why = await engine.begin(
        store, names=names, repo_key=where[0], cwd=where[1], given=block.input
    )
    if made is None:
        return HTMLResponse(_a_sentence(f"It did not start: {why}"))
    await store.finish_block(block.id, f"{said}\n\nStarted.")
    return HTMLResponse(_a_sentence(f"Running {len(names)} cards against what you typed."))


@router.post("/blocks/{block_id}/meant", response_class=HTMLResponse)
async def say_what_was_meant(block_id: str, request: Request) -> Response:
    """Which of the readings it was, said by the person the console asked.

    Only for a block that asked. A route that could re-run any block as anything would be a way to
    start an agent from a question somebody asked yesterday, which is the thing the asking exists
    to prevent.
    """
    block = await store.block(block_id)
    if block is None or block.kind != "unsure":
        return HTMLResponse(await render_blocks(), status_code=404)
    kind = str((await _form(request)).get("kind", "")).strip()
    rows, _ = await asyncio.to_thread(board)
    await block_runs.take_it_as(store, block, rows, kind)
    if _wants_fragment(request):
        return HTMLResponse(await render_blocks())
    return RedirectResponse("/", status_code=303)


@router.post("/blocks/{block_id}/answer-it", response_class=HTMLResponse)
async def answer_it_instead(block_id: str, request: Request) -> Response:
    """ "That was not an idea — write it." The correction that was missing.

    Both directions now exist, and they are not symmetrical. A request taken as an idea is
    silently not done: nothing was written, and it went into a list of things to build. A thought
    taken as a question costs one wasted answer. So this is the one whose absence was expensive.
    """
    block = await store.block(block_id)
    if block is None:
        return HTMLResponse(await render_blocks(), status_code=404)
    if block.kind == "idea":
        rows, _ = await asyncio.to_thread(board)
        await block_runs.answer_it_instead(store, block, rows)
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


async def _start_it(task: Task) -> None:
    """Start an agent on one claimed task, exactly the way the loop would.

    One function, because there are now two doors to it — the start button on a project's queue
    and "build it" on an idea — and two copies of "how a task becomes an agent" is two places for
    the briefing to fall out of step with what `autostart` sends.

    The task must already be claimed: `take_next_task` is the claim, and calling this on an
    unclaimed one would start a second agent on work another tick is holding.
    """
    result = await asyncio.to_thread(
        dispatch.start,
        dispatch.build_task(
            task.instruction,
            project=task.title,
            **await autostart.about(store, task.repo_key),  # type: ignore[arg-type]
        ),
        cwd=task.cwd,
        name=task.title,
    )
    if result.started:
        await store.task_started(task.id, result.agent_id)
    else:
        await store.task_failed(task.id, result.detail)


# One slot, holding the last state an idea was moved out of. Not a history: undoing the last
# thing is the whole of what somebody reaches for, and a stack of them is a second way to change
# state that nobody asked for. A setting rather than a column, because it is one row that is
# rewritten constantly and means nothing an hour later (CLAUDE.md, "simplicity first").
UNDO_KEY = "idea_undo"


# Three fields with no nesting in them, so `id|state|action` rather than JSON. Not only because
# it is smaller: `json.load` anywhere outside `observe/` is what `test_structure` refuses, on the
# grounds that parsing JSON in this program almost always means parsing a format Claude Code owns
# (docs/adr/0004). Reaching for a whitelist to store three words would have widened a real guard
# for no reason.
async def _remember_undo(idea: Idea, action: str) -> None:
    await store.set_setting(UNDO_KEY, f"{idea.id}|{idea.state}|{action}")


async def _undo_says() -> tuple[str, str, str]:
    """What the last state change was, as (idea id, the state to put back, the word for it)."""
    said = (await store.setting(UNDO_KEY)).split("|")
    return tuple(said) if len(said) == 3 else ("", "", "")  # type: ignore[return-value]


@router.post("/ideas/undo", response_class=HTMLResponse)
async def undo_idea(request: Request) -> Response:
    """Put back the state the last action moved an idea out of.

    Discard is one press and the idea leaves the column; before this the only way back was to go
    and find it in the inbox, which is a different page and a different frame of mind. The state
    it is put back into is the one this program recorded, not one the browser sends — a form field
    naming a state would be a way to set any state from anywhere.
    """
    idea_id, was, _ = await _undo_says()
    idea = await store.idea(idea_id) if idea_id else None
    if idea is not None and was in ("new", "kept", "promoted", "dropped", "done"):
        await store.set_idea_state(idea.id, was)  # type: ignore[arg-type]
    await store.set_setting(UNDO_KEY, "")
    if _wants_fragment(request):
        return HTMLResponse(await render_ideas())
    return RedirectResponse("/", status_code=303)


async def _build_it(idea: Idea) -> None:
    """Put one idea in its project's queue, as approved work (docs/adr/0006, 0007).

    Where it runs is resolved now rather than remembered: a queue holding a path that has since
    moved starts an agent in the wrong directory. An idea pointed at no project, or at one with no
    checkout on this machine, queues nothing — there is nowhere to do it, and inventing a
    destination would be worse than the button doing nothing visible.
    """
    if not idea.project_key:
        return
    rows, _ = await asyncio.to_thread(board)
    projects = shape(rows, await store.groups())
    named = next((one for one in projects if one.key == idea.project_key), None)
    if named is None or not named.instances:
        return
    await store.queue_task(
        repo_key=named.key,
        cwd=named.instances[0].path,
        title=idea.summary[:60],
        instruction=idea.text,
        source_kind="idea",
        # What gets marked built when its agent finishes (agent_desk/web/autostart.py).
        source_ref=idea.id,
    )

    # And if the project is switched on, it starts here rather than up to a minute later when the
    # loop next comes round. Pressing a button and watching nothing happen is the wrong answer to
    # "build it", and the switch is where somebody already said this project may start work by
    # itself (docs/adr/0007).
    #
    # `why_not` rather than a second opinion about it: it is the same function the loop asks, so
    # the seat rule, the hour's budget and the arming state are answered once. A project that may
    # not start right now keeps the task queued, which is what the queue is for.
    if await autostart.why_not(store, named.key):
        return
    # The oldest waiting task, which may not be this one. That is the queue's own contract and
    # breaking it here would be the surprise in the other direction — a button that jumps the
    # line. Either way an agent is now working in this project, which is what was asked for.
    claimed = await store.take_next_task(named.key)
    if claimed is not None:
        await _start_it(claimed)


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
    if action not in ("keep", "drop", "done", "summary", "build", "later", "shape", *DRAFT_KINDS):
        # An action this program does not have is a mistake somewhere, not something to redirect
        # away from quietly — that is how a typo becomes a mystery.
        # The segment is not echoed back: reflecting an unvalidated path into a response is a
        # habit worth not having, even where the content type makes it harmless.
        return PlainTextResponse("no such action", status_code=404)

    # The templates hide a button that does not apply; the route has to mean it. Keeping an idea
    # that was already promoted quietly walked it backwards through its own four states.
    #
    # `build`, `later` and `shape` are decisions rather than states, which is why they sit beside
    # the four rather than among them: "build it" says when the work happens, "later" says when to
    # be asked again, and "shape" answers a question a background pass asked about the text. None
    # of them is a step along `new → kept → promoted`, and a person may take any of them at any
    # point before the idea is out of the pool.
    decisions = {"build", "later", "shape"}
    allowed = {
        "new": {"keep", "drop", "done", "summary"} | decisions,
        "kept": {"drop", "done", "summary", *DRAFT_KINDS} | decisions,
        "promoted": {"done", "summary", *DRAFT_KINDS} | decisions,
        "dropped": {"keep", "summary"},
        # Built is not final: a human who finds it was not, after all, says so with Keep.
        "done": {"keep", "summary"},
    }[idea.state]
    if action not in allowed:
        return PlainTextResponse(f"an idea that is {idea.state} cannot do that", status_code=409)

    if action in ("keep", "drop", "done"):
        # Before it moves, so there is somewhere to put it back to.
        await _remember_undo(idea, action)
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
    elif action == "build":
        # The decision the column was missing. Everything else here recorded what somebody thought
        # about an idea; nothing turned one into work, and the only door that did went through a
        # message ("бери в работу") and the classifier. Approval and dispatch in one press is what
        # docs/adr/0006 permits a human to do, and the queue is what docs/adr/0007 says it lands
        # in: this puts it there, and the arming switch decides whether an agent starts on it now.
        await _build_it(idea)
    elif action == "later":
        # "Отложенная задача должна иметь момент срабатывания." The machinery is
        # agent_desk/web/later.py; this is the button that reaches it, and the phrase is read by
        # the same function that reads one out of a typed message, so the two cannot drift.
        wake = waking.read(form.get("when", "").strip(), now=datetime.now(UTC))
        if wake is not None:
            await store.defer_idea(idea_id, at=wake.at, when=wake.when)
        elif form.get("when", "").strip() == "never":
            # Taking a deferral off is the same button with nothing in it.
            await store.defer_idea(idea_id, at=None, when=None)
    elif action == "shape":
        # The answer to a question the appraisal pass asked. "This reads like something that
        # already exists — is it?" had no buttons under it: the card raised the doubt and left
        # somebody to resolve it somewhere else, which mostly meant not at all.
        said = form.get("shape", "").strip()
        if said in ("build", "decide", "built", "none"):
            await store.set_idea_shape(idea_id, "" if said == "none" else said)
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
