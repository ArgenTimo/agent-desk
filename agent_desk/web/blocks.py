"""The input field, and what it produces.

Submitting frees the field. What was typed becomes a *block* that prepares its own answer on its
own time, and the next thing can be typed while it does — a chat is a queue, and these are
unrelated errands that happen to be typed by the same person in the same minute
(docs/04-threads-and-blocks.md).

Runs live in one `TaskGroup` held open for the life of the process. A bare `create_task` produces
a failure nobody observes; a task group observes them. Each run also catches its own failures and
writes them to the store, so one question going wrong never tears down the group answering the
other five.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import re
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from agent_desk import (
    dispatch,
    finding,
    handling,
    looking,
    pasted,
    process,
    roles,
    showing,
    telling,
    ties,
)
from agent_desk import secrets as kept
from agent_desk.answer import classify as classifier
from agent_desk.answer import session
from agent_desk.ideas import appraise, inbox, kin
from agent_desk.observe import reading
from agent_desk.observe.model import Session
from agent_desk.store.redact import scrub
from agent_desk.store.repo import (
    BenchCard,
    Block,
    BoardTicket,
    DraftKind,
    Idea,
    Pull,
    Store,
    Thread,
    TicketLink,
)
from agent_desk.tracker import github, jira
from agent_desk.web import engine

if TYPE_CHECKING:
    from agent_desk.web.routes import BoardRow

# What a running block has said so far. Memory only, and dropped the moment the block finishes:
# the store holds the answer, and a partial answer is a second copy of a thing already redacted
# once (design/02-data-model.md, "What is deliberately not stored").
PARTIAL: dict[str, str] = {}

# What a running block is *doing*, as opposed to what it has said. One line, replaced each time the
# run reaches for a tool: "reading store/repo.py", "searching for keep_bench".
#
# "Длинный ответ, который возникает целиком через сорок секунд, читается как зависание." A turn
# that only used a tool produces no text at all, so a run that spends thirty seconds looking
# through a repository streams nothing — and a caret blinking on an empty line for half a minute
# is indistinguishable from a console that has stopped.
#
# Memory only and dropped when the block finishes, for the same reason as PARTIAL: this is a note
# about a run in progress, and there is no question it answers once the run is over.
DOING: dict[str, str] = {}

# Ideas whose draft is being written, so the inbox can say "drafting" instead of showing a click
# that appeared to do nothing. Memory only, for the same reason as PARTIAL.
DRAFTING: set[tuple[str, str]] = set()

# Prefixes for when you already know what you want (docs/06-console.md). `/idea` skips
# classification entirely; `/new` forces a new thread, which is what every question gets until the
# classifier exists to propose otherwise.
IDEA_PREFIX = "/idea"
NEW_PREFIX = "/new"


class Runs:
    """Blocks in flight.

    Wraps the process-wide `TaskGroup` so that a route can start a run without holding the group,
    and so that shutdown can end them rather than wait for them — the console must stop when a
    human asks it to, even with three questions in the air.
    """

    def __init__(self) -> None:
        self._group: asyncio.TaskGroup | None = None
        self._by_block: dict[str, asyncio.Task[None]] = {}

    def attach(self, group: asyncio.TaskGroup | None) -> None:
        self._group = group

    @property
    def running(self) -> bool:
        """Is there a group to start a run in?

        Asked by the one caller that starts a run nobody clicked for — the write-up drafted when
        an idea is kept. Every other caller is behind a click that only exists while the console
        is up, and a click that cannot run is a bug rather than a state to check for.
        """
        return self._group is not None

    def start(self, block_id: str, make: Callable[[], Coroutine[object, object, None]]) -> None:
        """Start one run, replacing any run already in flight for the same block.

        Two things here are the difference between a console and a console that dies.

        A second run for one block used to orphan the first: the map was overwritten, the first
        task's callback then removed the *second* entry, and two `claude -p` processes raced to
        write one row while `cancel` reported success over the wrong one. Reachable by moving a
        block between threads while it was still running.

        And a child that raises takes a `TaskGroup` down with it, which here means the input
        field, every other run and the lifespan. One question going wrong must never do that, so
        every run is wrapped: `CancelledError` propagates, everything else is logged against the
        block it came from and stops there.
        """
        if self._group is None:  # pragma: no cover - the app always attaches one
            raise RuntimeError("no task group is running")

        previous = self._by_block.get(block_id)
        if previous is not None and not previous.done():
            # A defensive net only: the callers below await `stop` first, because cancelling here
            # and starting the replacement in the same breath is a race the old run wins half the
            # time — its shielded `cancelled` write lands after the new run's `running`, and the
            # console then shows a cancelled block with a live subprocess behind it.
            log.warning("a run was replaced without being stopped first", block=block_id)
            previous.cancel()

        task = self._group.create_task(self._contained(block_id, make))
        self._by_block[block_id] = task
        task.add_done_callback(lambda done: self._forget(block_id, done))

    def _forget(self, block_id: str, done: asyncio.Task[None]) -> None:
        """Only the task that is still the current one may remove itself."""
        if self._by_block.get(block_id) is done:
            del self._by_block[block_id]

    @staticmethod
    async def _contained(
        block_id: str, make: Callable[[], Coroutine[object, object, None]]
    ) -> None:
        # The run is built here rather than at the call site, so that a task cancelled before its
        # first step leaves no coroutine that was created and never awaited. The block's own state
        # is written by `cancel`, which is the only place that knows it happened.
        try:
            await make()
        except asyncio.CancelledError:
            raise
        except Exception:
            # The block already carries its own failure where the failure was expected; this is
            # for the ones that were not, and it exists so that the group survives them.
            log.exception("a run raised outside its own error handling", block=block_id)

    def cancel(self, block_id: str) -> bool:
        task = self._by_block.get(block_id)
        if task is None:
            return False
        task.cancel()
        return True

    async def stop(self, block_id: str) -> bool:
        """Cancel a run and wait for it to be gone before anything replaces it."""
        task = self._by_block.get(block_id)
        if task is None:
            return False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return True

    async def stop_all(self) -> list[str]:
        """Shutdown ends runs rather than waiting for them, and says which it ended.

        A console that will not stop while three questions are in the air is the shutdown hang
        this project already fixed once, in a different disguise.

        Cancelled together and then awaited, which is the half that was missing. A cancelled run
        writes its own `cancelled` row under a shield; the caller then writes one too, for the run
        that was cancelled before its first step. Without the wait those two writes are in flight
        at the same moment, and SQLite answers the second with "database is locked" — five seconds
        of busy-wait, twice, and a console that took eleven seconds to close. It was not a hang and
        it was not rare: one shutdown in four, measured by running the test that asserts this.

        Every cancellation is delivered before anything is awaited, so this is still "end them"
        and not "wait for them": the wait is on tasks that have already been told to stop, and
        each is bounded by the reap in `answer/session.py`.
        """
        stopped = list(self._by_block)
        tasks = list(self._by_block.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        return stopped

    def __len__(self) -> int:
        return len(self._by_block)


runs = Runs()

log = structlog.get_logger("agent_desk.blocks")


def _add_dirs(sessions: Sequence[Session]) -> list[Path]:
    """The repositories being observed, deduplicated, for the run to read (docs/04)."""
    seen: dict[str, Path] = {}
    for live in sessions:
        directory = Path(live.cwd)
        if directory.is_dir():
            seen.setdefault(live.cwd, directory)
    return list(seen.values())


def board_lines(rows: Sequence[BoardRow]) -> list[str]:
    """The board as the run will read it: one line a session, facts only.

    The inference is deliberately absent. "May be waiting for you" is this program's guess, and
    feeding a guess to a model that will then reason from it is how a guess becomes a fact
    (docs/03-session-observation.md).
    """
    lines = []
    for row in rows:
        title = (row.tail.title if row.tail else None) or "no title read"
        branch = (row.tail.git_branch if row.tail else None) or "—"
        last = row.tail.last_entry if row.tail else None
        line = f'- {row.session.project} · {branch} · {row.session.status} · "{title}"'
        if last is not None:
            line += f" · last entry {last.role}: {last.text[:200]}"
        lines.append(line)
    return lines


def _capture_context(rows: Sequence[BoardRow]) -> tuple[str, str | None, dict[str, str]]:
    """What was happening when the thought arrived (docs/05-ideas.md).

    A typed idea is attached to a session only when there is exactly one to attach it to. With
    several running, "the session that was running" is a guess, and an idea remembered against the
    wrong branch is worse a week later than one remembered against none — so the board is
    described instead, and the source stays `typed`.
    """
    if len(rows) == 1:
        row = rows[0]
        return (
            "session",
            row.session.session_id,
            {
                "project": row.session.project,
                "branch": (row.tail.git_branch if row.tail else None) or "—",
                "title": (row.tail.title if row.tail else None) or "no title read",
            },
        )
    return (
        "typed",
        None,
        {
            "sessions": str(len(rows)),
            "projects": ", ".join(sorted({row.session.project for row in rows})) or "none",
        },
    )


async def capture_idea(store: Store, text: str, rows: Sequence[BoardRow]) -> Block:
    """`/idea`: recorded in one step, with a card and no second question (docs/05-ideas.md).

    The block is `answered` the moment it exists, because it is. The idea is written before any
    model is asked anything, which is the property this module is for: the run is the part that
    can fail. What runs afterwards improves the summary, or — when the message held several
    thoughts — takes it apart into one idea each.
    """
    source_kind, source_ref, context = _capture_context(rows)
    thread = await store.create_thread(inbox.fallback_summary(text) or "an idea")
    block = await store.create_block(
        thread_id=thread.id, kind="idea", input=text, thread_set_by="human"
    )
    idea = await inbox.capture(
        store,
        text,
        source_kind=source_kind,  # type: ignore[arg-type]
        source_ref=source_ref,
        context=context,
        block_id=block.id,
        project_key=project_of(rows),
    )
    await store.finish_block(block.id, "")
    # An idea block asks nothing further, so its subject is not a candidate for a later question
    # to be attached to — and an idea's summary makes a confusing thread title anyway.
    await store.close_thread(thread.id)
    runs.start(f"capture:{block.id}", lambda: _write_ideas(store, block, idea, rows))
    return block


async def _write_ideas(store: Store, block: Block, whole: Idea, rows: Sequence[BoardRow]) -> None:
    """Take the message apart, if it was several thoughts, and write each of them down.

    "Add A, B is broken, and we should probably C" is one message and three ideas, and a person
    typing at speed does not stop to send three messages. This runs *after* the thought is safe:
    the whole message is already an idea in the store, and what happens here either improves its
    summary or replaces it with the ideas it turned out to contain. Failing changes nothing, which
    is why it is allowed to be a model call at all (docs/05-ideas.md).
    """
    try:
        reply = "".join(
            [chunk async for chunk in session.stream_answer(inbox.split_prompt(whole.text))]
        )
        parts = inbox.read_split(reply, whole.text)
    except (session.AnswerFailed, OSError):
        parts = [whole.text]

    if len(parts) < 2:
        # One thought, which is the ordinary case: it gets the generated summary line it has
        # always got, and the text it was typed as — and then the notebook is asked whether it
        # already has this one (agent_desk/ideas/kin.py).
        await _summarise(store, whole)
        await _place(store, whole)
        return

    # A human who has already touched this card has said what they want it to be, and a splitter
    # arriving afterwards does not get to disagree — the same rule the summary follows.
    current = await store.idea(whole.id)
    if current is None or current.state != "new" or current.summary != whole.summary:
        return

    # The message stays, and the thoughts hang under it. It is one thing somebody typed and
    # several things they meant, and a week later "what was I saying" reads as the first rather
    # than as three fragments in a row (docs/05-ideas.md).
    source_kind, source_ref, context = _capture_context(rows)
    for part in parts:
        written = await inbox.capture(
            store,
            part,
            source_kind=source_kind,  # type: ignore[arg-type]
            source_ref=source_ref,
            context=context,
            block_id=block.id,
            project_key=project_of(rows),
            parent_id=whole.id,
        )
        # And then: is this one already in the notebook? (agent_desk/ideas/kin.py) It runs here
        # rather than inside `capture` for the reason every model call in this file runs after the
        # write — a list with one honest duplicate in it beats a capture that failed.
        await _place(store, written)


async def _place(store: Store, idea: Idea) -> None:
    """Put a freshly captured idea where it belongs, and never fail the capture over it."""
    try:
        where = await kin.suggest(store, idea)
    except Exception:  # a judgement that fails leaves the row exactly where it is
        log.warning("ideas.place_failed", idea=idea.id)
        return
    if where != "new":
        log.info("ideas.placed", idea=idea.id, where=where)


async def _summarise(store: Store, idea: Idea) -> None:
    """Replace the fallback line if a run produces a better one. Never fail the capture over it.

    One implementation, in `ideas/appraise.py`, because the sweep tries this again when the model
    was unavailable here — and two copies of "what may overwrite a card's line" would disagree
    about a person's own words the first time either moved.
    """
    await appraise.better_summary(store, idea)


async def draft(store: Store, idea: Idea, kind: DraftKind) -> None:
    """One of the three actions of docs/05-ideas.md. All three produce text in this tool."""
    if kind == "paste":
        await store.create_draft(idea_id=idea.id, kind=kind, body=inbox.paste_body(idea))
        return

    # Keyed by idea *and* kind: a proposal and a ticket in flight together used to share one flag,
    # so the first to finish told the inbox the second was done too.
    DRAFTING.add((idea.id, kind))
    runs.start(f"draft:{idea.id}:{kind}", lambda: _draft(store, idea, kind))


async def _draft(store: Store, idea: Idea, kind: DraftKind) -> None:
    try:
        prompt = inbox.PROMPTS[kind](idea)
        body = "".join([chunk async for chunk in session.stream_answer(prompt)]).strip()
        if body:
            await store.create_draft(idea_id=idea.id, kind=kind, body=body)
    except (session.AnswerFailed, OSError) as exc:
        await store.create_draft(
            idea_id=idea.id,
            kind=kind,
            body=f"The draft could not be written: {exc}\n\nThe idea itself is unharmed above.",
        )
    finally:
        DRAFTING.discard((idea.id, kind))


def _rows_named(rows: Sequence[BoardRow], kind: str, ident: str) -> tuple[list[BoardRow], str]:
    """The sessions one card stands for, and what to call it.

    Four kinds resolve to sessions, because a session is the only thing there is evidence about:
    an agent names the console it runs inside, an instance names a checkout, a project names a
    repository. A card whose session has since ended resolves to nothing and is skipped —
    silently, because a question asked a second after a session ended should still be answered.
    """
    if kind in ("session", "agent"):
        found = [row for row in rows if row.session.session_id == ident]
        return found, f"{found[0].session.project} · {found[0].session.name}" if found else ""
    if kind == "instance":
        found = [row for row in rows if row.session.cwd == ident]
        return found, found[0].session.project if found else ""
    if kind == "project":
        found = [row for row in rows if row.project_key == ident]
        return found, found[0].project_name if found else ""
    return [], ""


def _card(target: str) -> tuple[str, str, bool]:
    """One dropped card: `kind:id`, or `kind:id:full` when its whole transcript was asked for."""
    kind, _, rest = target.partition(":")
    if rest.endswith(":full"):
        return kind, rest[: -len(":full")], True
    return kind, rest, False


def _targets(rows: Sequence[BoardRow], dropped: Sequence[str]) -> tuple[list[BoardRow], str]:
    """The rows named by the cards sitting in the output field, in the order they were dropped."""
    chosen: list[BoardRow] = []
    labels: list[str] = []
    for target in dropped:
        kind, ident, _ = _card(target)
        found, label = _rows_named(rows, kind, ident)
        for row in found:
            if row not in chosen:
                chosen.append(row)
        if label and label not in labels:
            labels.append(label)
    return chosen, ", ".join(labels)


async def _half_of_an_exchange(
    store: Store, kind: str, ident: str, role: str
) -> looking.OnBench | None:
    """A question card or an answer card, put on the bench because a gesture named it.

    Both are ordinarily left out, and for a good reason: they are the conversation, which is in the
    prompt already as the thread. But a card somebody dragged onto another card is not being
    carried along — it is being pointed at, and the model has to be able to see two things where
    two were named. Without this the second step of a chain answered "there is only one card in
    front of you", which is the chain ending at step two.
    """
    block = await store.block(ident)
    if block is None:
        return None
    said = (block.answer or "") if kind == "answer" else block.input
    if not said.strip():
        return None
    return looking.OnBench(
        name=f"{kind}:{ident}",
        kind=kind,
        label=said.strip().splitlines()[0][:60],
        said=said,
        role=role,
    )


async def on_the_bench(
    store: Store, rows: Sequence[BoardRow], dropped: Sequence[str], named: Sequence[str] = ()
) -> looking.Look:
    """The cards in front of this question, as the model is shown them (agent_desk/looking.py).

    Gathered here because this is where the store and the board both are; what to *do* with them is
    `looking`'s, which is pure and therefore testable without either.

    What is written on a card comes from the best source that kind has, and the order is not
    arbitrary — it is most-specific first. An idea's own words beat any sentence written about it,
    because a person wrote them and a pass did not. A session's description beats the headline it writes
    about itself, which beats its last line: "rewriting the registry reader" says what it is, and
    "npm ERR!" says what happened to scroll past a second before somebody asked.
    A card with nothing behind it contributes its label and no invented sentence, which is what
    "nobody has looked at this yet" is supposed to look like (CLAUDE.md, rule five).

    A block card is left out, and so is an answer card — the two halves of one exchange, which is
    already in the prompt twice over as the thread's history. Listing either again as a card would
    have the model reason about the conversation as a thing on the bench.

    Unless it is in `named`, which is the cards a *gesture* pointed at rather than the cards a
    message happened to be carrying. Dragging a result onto another card is somebody saying "these
    two", and a digest that then describes one of them is a digest that cannot be answered.
    """
    # A card a *gesture* named is here because the gesture named it. It used to have to appear in
    # `dropped` as well, which meant the page had to keep sending every block card on the bench in
    # case one of them turned out to be half of a combine — and that is why the count under the
    # bench said thirty-seven where the model saw twenty-seven. A coupling, not a rule.
    dropped = [*dropped, *(one for one in named if one not in set(dropped))]
    names = [f"{kind}:{ident}" for kind, ident, _ in map(_card, dropped)]
    said = await store.cards_said(names)
    chosen = await store.card_roles()
    ideas = {f"idea:{one.id}": one for one in await store.ideas()}
    steps = {one.name: one.label for one in await store.step_cards()}
    cards: list[looking.OnBench] = []
    seen: set[str] = set()
    for target in dropped:
        kind, ident, _ = _card(target)
        name = f"{kind}:{ident}"
        if not ident or name in seen:
            continue
        if kind in ("block", "answer"):
            if name not in named:
                continue
            seen.add(name)
            half = await _half_of_an_exchange(store, kind, ident, chosen.get(name, ""))
            if half is not None:
                cards.append(half)
            continue
        if kind == "check":
            # A check card carries its condition and, once pressed, its verdict. Both belong in the
            # prompt of anything asked with one in front of it: an attempt that cannot see what it
            # failed is an attempt at the same answer (062-a-card-that-checks.sql).
            seen.add(name)
            checked = await store.check_card(ident)
            if checked is not None:
                cards.append(
                    looking.OnBench(
                        name=name,
                        kind="check",
                        label=checked.label,
                        said=(
                            f"it has to be: {checked.said}"
                            + (f" — last time {checked.why}" if checked.verdict else "")
                            # What a person said about that verdict, in the words the machine did
                            # not have. This is the whole of why a comment is not a note in the
                            # margin: it is in the prompt of the next attempt (064).
                            + (f" — and a person adds: {checked.note}" if checked.note else "")
                        ),
                        role=chosen.get(name, ""),
                    )
                )
            continue
        seen.add(name)
        idea = ideas.get(name)
        if idea is not None:
            cards.append(
                looking.OnBench(
                    name=name,
                    kind="idea",
                    label=idea.summary,
                    said=idea.text,
                    role=chosen.get(name, ""),
                )
            )
            continue
        found, label = _rows_named(rows, kind, ident)
        about = said.get(name, "")
        if not about and found and found[0].tail is not None:
            tail = found[0].tail
            about = tail.title or (tail.last_entry.text if tail.last_entry else "")
        cards.append(
            looking.OnBench(
                name=name,
                kind=kind,
                label=label or steps.get(name) or ident,
                said=about,
                role=chosen.get(name, ""),
            )
        )
    ties_ = [(tie.from_name, tie.to_name, tie.says or tie.kind) for tie in await store.card_ties()]
    return looking.look(cards, ties_)


# How much of one transcript a card marked `full` is allowed to contribute. The tail itself is
# already bounded when it is read (docs/03-session-observation.md); this bounds what three of them
# together can do to one prompt.
DEEP_ENTRIES = 40


def transcripts(rows: Sequence[BoardRow], dropped: Sequence[str]) -> list[str]:
    """The whole of what was read for the cards somebody asked the whole of.

    A card contributes one line by default — enough to know what it is, and cheap enough that ten
    of them cost nothing. Asking for its transcript is a separate act with a visible control,
    because the difference between the two is the size of the prompt and how long the answer
    takes ([docs/04-threads-and-blocks.md](../../docs/04-threads-and-blocks.md)).
    """
    lines: list[str] = []
    seen: set[str] = set()
    for target in dropped:
        kind, ident, deep = _card(target)
        if not deep:
            continue
        for row in _rows_named(rows, kind, ident)[0]:
            if row.session.session_id in seen or row.tail is None:
                continue
            seen.add(row.session.session_id)
            lines.append("")
            lines.append(f"### {row.session.project} · {row.session.name}")
            for entry in row.tail.entries[-DEEP_ENTRIES:]:
                lines.append(f"{entry.role}: {entry.text}")
    return lines


def aim(
    rows: Sequence[BoardRow],
    project: str = "",
    session: str = "",
    targets: Sequence[str] = (),
) -> tuple[Sequence[BoardRow], str]:
    """Narrow the board to what the question was pointed at, and say so in a line.

    Three cases, and the third is the default (docs/06-console.md). Cards dropped into the output
    field: those, in the order they were dropped. A session or a project named outright: that one.
    Neither: the whole board, and the run works out from it what the question is about — which is
    what somebody who has not chosen wants, rather than an error asking them to choose.

    A target that no longer exists falls back to the whole board rather than to nothing: sessions
    end, and a question asked a second after one did should still be answered.
    """
    if targets:
        chosen, label = _targets(rows, targets)
        if chosen:
            return chosen, f"what was dropped in: {label}"
    if session:
        chosen = [row for row in rows if row.session.session_id == session]
        if chosen:
            row = chosen[0]
            return chosen, f"one session: {row.session.project} · {row.session.name}"
    if project:
        chosen = [row for row in rows if row.project_key == project]
        if chosen:
            return chosen, f"one project: {chosen[0].project_name}"
    return rows, ""


@dataclass(frozen=True)
class Carried:
    """What a workbench contributes to a question, before the question is written.

    Three lists rather than one because the prompt puts them in different places: the digest of the
    cards, what those cards *say*, and the names in the order the digest numbered them — so an
    answer that says "3" and a card on the bench are the same card (agent_desk/handling.py).
    """

    surface: list[str]
    written: list[str]
    on_bench: list[str]
    # Cards there was no room for in the digest. Carried out of `looking.Look` rather than counted
    # again here: "why did it not know about X" is the other half of "why did it say that", and the
    # only place that knows the answer is the thing that did the cutting.
    left_out: int = 0


async def carried_from_the_bench(
    store: Store,
    rows: Sequence[BoardRow],
    targets: Sequence[str],
    named: Sequence[str] = (),
) -> Carried:
    """Gather what these cards carry into a question.

    One function because two callers need the same answer and one of them is not a browser: the
    console gathers it when somebody presses send, and an agent asking for a workbench over MCP is
    asking for this and nothing else (`agent_desk/mcp/tools.py`). A second gatherer would be a
    second set of rules about which files may be read, and that is the rule this program most
    cannot afford to have two of.

    `targets` is what the question is pointed at — the cards somebody chose, or the whole bench
    when they chose none. Nothing here widens it.
    """
    look = await on_the_bench(store, rows, targets, named)
    return Carried(
        surface=looking.as_lines(look),
        written=await notes(store, targets),
        on_bench=[card.name for card in look.cards],
        left_out=look.left_out,
    )


def as_one_string(carried: Carried) -> str:
    """The same text a question would carry, in the same words and the same order.

    Built out of the prompt's own section builders rather than out of a copy of them, so that what
    an agent is handed is a piece of the prompt and can be checked to be one.
    """
    return "\n".join(
        session.workbench_section(carried.surface) + session.carried_section(carried.written)
    ).strip("\n")


async def submit(
    store: Store,
    typed: str,
    rows: Sequence[BoardRow],
    *,
    project: str = "",
    session: str = "",
    targets: Sequence[str] = (),
    thread_id: str = "",
    history: Sequence[str] = (),
    notes_: str = "",
    made_from: Sequence[str] = (),
    a_gesture: bool = False,
) -> Block:
    """Accept one line of input and start working on it.

    `/idea` records instead of asking, in one step and with no model call in the way. `/new`
    forces a subject of its own.

    Everything else goes to a run that first decides *what was typed* — a question, a thought, or
    an instruction to a session — because those three want three different responses and the
    person typing should not have to say which they meant (docs/04-threads-and-blocks.md).

    `thread_id` is the tab it was typed in. A tab is a subject somebody chose by typing in it, so
    a block that arrives with one is not classified: that is the "default and a click" docs/09
    names as what should replace the classifier if it costs more attention than it saves.
    """
    text = typed.strip()
    if text.startswith(IDEA_PREFIX):
        return await capture_idea(store, text[len(IDEA_PREFIX) :].strip(), rows)
    forced_new = text.startswith(NEW_PREFIX)
    if forced_new:
        text = text[len(NEW_PREFIX) :].strip()

    # What the message is made of, and — before anything else touches it — any credential out of
    # it. A block's input goes into the database, onto the page, into the thread that travels with
    # the next question and into the prompt; a token left in it is in all four, and deleting the
    # message afterwards does not take it out of the two that already left (agent_desk/pasted.py).
    found = pasted.read(text)
    if found.token:
        # The store built for this, on this machine, mode 0600, never read back to a screen. The
        # value is dropped here and nothing else in this function has seen it.
        kept.keep(found.kept_as, found.token)
    text = found.said

    # The block exists before anything is classified or answered, and the field is free the moment
    # it does. It starts as a question because that is the safe reading of an unread line, and the
    # run corrects it in a second if it was something else.
    thread = await _thread_for(store, thread_id, text)
    block = await store.create_block(
        thread_id=thread.id, kind="question", input=text, thread_set_by="human"
    )
    # What the message turned out to hold, said rather than assumed: somebody who pasted four
    # things and got an answer about two needs to see which two, and a secret that was moved has
    # to say where it went.
    if found.repos:
        # The address, where a control can reach it (056). The offer to start a project from it is
        # a button; nothing here clones anything.
        await store.set_block_repo(block.id, found.repos[0])
    # Read here rather than after the record is written, and that order is the point: what a block
    # says it carried is now derived from the same reading the prompt is built from, so the two
    # cannot say different things. They did — a bench with one card named twice recorded four
    # things and asked with two, and the largest message in this store says it carried ninety-six
    # of which twenty-two are distinct. docs/04: a block that cannot say what it carried is a block
    # whose answer cannot be explained afterwards, and one that says ninety-six is worse than one
    # that says nothing, because somebody will reason from it.
    #
    # Read now rather than when the run reaches the prompt: this is what was in front of the person
    # when they pressed send, and a bench read a minute later is a different bench.
    bench = await carried_from_the_bench(store, rows, targets, made_from)
    written, surface, on_bench = bench.written, bench.surface, bench.on_bench
    carried = pasted.as_lines(found) + await _context_lines(
        store, rows, targets, history, carried=on_bench, left_out=bench.left_out
    )
    if notes_.strip():
        # Blocks somebody wrote on the workbench themselves — a link, a paragraph of a document, a
        # snippet of code. They are text rather than a card this console read, so they are carried
        # as text and named as the person's own, which is the difference an agent needs.
        carried = [*carried, "what they wrote on the workbench:", notes_.strip()]
    if carried:
        await store.set_block_context(block.id, "\n".join(carried))
    dropped_ideas = [_card(target)[1] for target in targets if _card(target)[0] == "idea"]
    if dropped_ideas:
        await store.link_block_ideas(block.id, dropped_ideas)
    aimed, about = aim(rows, project, session, targets)
    if a_gesture:
        # "Соединение стоит один вызов и происходит часто… дёшево и быстро." A combine is about two
        # cards and nothing else, so it carries neither. `aim` falls back to the whole board when
        # the cards it was pointed at are not sessions — which two ideas never are — and every
        # session on the machine was being described to a question that had nothing to do with any
        # of them. On a board with a dozen projects that is most of the prompt.
        aimed, about = [], ""

    deep = transcripts(rows, targets)
    classify = not forced_new and not thread_id
    runs.start(
        block.id,
        lambda: _work(
            store,
            block,
            aimed,
            classify=classify,
            # A gesture is not read. The console writes the words of a combine itself, so there is
            # nothing for a reader to work out — and when it was read it came back `master`, which
            # is the branch that starts an agent in a worktree. Twice, in a browser, from a drag.
            # Dragging one card onto another must not be able to start work, and the guard belongs
            # here rather than in the wording: a prompt phrased more carefully is a prompt the next
            # release of the classifier can read differently.
            a_gesture=a_gesture,
            about=about,
            deep=deep,
            history=list(history),
            written=[*written, notes_.strip()] if notes_.strip() else written,
            surface=surface,
            on_bench=on_bench,
            # What they were pointing at is part of what they said (agent_desk/answer/classify.py).
            pointed_at=len(targets),
        ),
    )
    return block


async def notes(store: Store, dropped: Sequence[str]) -> list[str]:
    """What the cards carried into a question say, as text.

    Two kinds of card say anything here. An idea has no board row and no transcript: what it
    contributes is what somebody wrote down and why. A file contributes its contents, and only when
    somebody has said that it may — the rest of the time a file on the bench is a name, which is
    what a folder card is and why dropping a directory here is safe.

    Dropping an idea in is how "does this still make sense given what these two sessions did" gets
    asked; dropping three files in and allowing them is how "make me something out of these" does.
    """
    lines: list[str] = []
    for target in dropped:
        kind, ident, _ = _card(target)
        if kind == "idea":
            idea = await store.idea(ident)
            if idea is not None:
                lines.append(f"- {idea.summary}: {idea.text}")
            continue
        # A file says nothing until somebody said it may (055). Not a check that can be forgotten
        # into an accident: the default is silence, and the permission is a row somebody made.
        if kind == "file" and await store.may_be_read(ident):
            said = reading.read_file(ident)
            if said.ok:
                # Scrubbed like everything else that leaves this program. They asked for the file
                # to be read, not for the token in line 40 of it to be sent (docs/07-security.md).
                lines.append(f"- {ident}:\n{scrub(said.text)}")
    return lines


async def _context_lines(
    store: Store,
    rows: Sequence[BoardRow],
    targets: Sequence[str],
    history: Sequence[str],
    *,
    carried: Sequence[str],
    left_out: int = 0,
) -> list[str]:
    """What this question is being sent with, in the words the console used for it.

    Written before the run starts, so that a block that is still answering can already say what it
    was given. "Why did it say that" is a question about the context, and the context was a
    decision somebody made in a second and has already forgotten.

    `carried` is the cards `on_the_bench` actually built the prompt from, and it is required rather
    than optional. This function used to walk `targets` on its own, which made it a *second*
    reading of "what does this message carry" — and a second reading of one question is two answers
    to it. It gave two: a card named twice was recorded twice while the prompt saw it once, and a
    block card that `on_the_bench` deliberately leaves out was recorded as carried, on this console
    as `block · no longer on the board`, which reads like something went wrong.

    What is still decided here is the *wording* — how many sessions a name matched, whether a whole
    transcript went. What is decided by `on_the_bench` is which cards there are, which is the part
    that must not be answered twice.
    """
    # Walked in the prompt's order and not the browser's, because the prompt numbers these cards
    # and a record in a different order is a record whose third line is not the model's third card.
    # `targets` is consulted only for what it alone knows: whether a whole transcript went.
    whole = {f"{kind}:{ident}" for kind, ident, deep in map(_card, targets) if deep}
    lines: list[str] = []
    for name in carried:
        kind, _, ident = name.partition(":")
        deep = name in whole
        if kind == "idea":
            idea = await store.idea(ident)
            lines.append(f"idea · {idea.summary}" if idea else "idea · no longer in the inbox")
            continue
        found, label = _rows_named(rows, kind, ident)
        if not found:
            lines.append(f"{kind} · no longer on the board")
            continue
        said = " · whole transcript" if deep else ""
        lines.append(
            f"{kind} · {label} ({len(found)} session{'' if len(found) == 1 else 's'}){said}"
        )
    for block_id in history:
        earlier = await store.block(block_id)
        if earlier is not None:
            lines.append(f"earlier · {earlier.input[:80]}")
    # And what did not go, which is the other half of the question this record is kept to answer.
    # Two reasons a card is missing from the list above, and they are not the same reason: one is a
    # budget and the other is a rule, so a record that reported them as one number would be telling
    # somebody the digest was full when nothing had been cut.
    conversation = sum(
        1
        for kind, ident, _ in map(_card, targets)
        if kind in ("block", "answer") and f"{kind}:{ident}" not in set(carried)
    )
    if conversation:
        lines.append(
            f"not listed · {conversation} card{'' if conversation == 1 else 's'} of this "
            "conversation, which travel as the thread's own history"
        )
    if left_out:
        lines.append(
            f"not listed · {left_out} more card{'' if left_out == 1 else 's'} that did not fit "
            "the digest"
        )
    return lines


async def _thread_for(store: Store, thread_id: str, text: str) -> Thread:
    """The tab this was typed in, or a subject of its own.

    A tab that has been closed or that never existed — a stale page posting an id the store has
    forgotten — falls back to a new subject rather than to an error: the input field's first
    promise is that typing costs nothing.
    """
    if thread_id:
        for thread in await store.open_threads():
            if thread.id == thread_id:
                # A chat that has not been about anything yet takes the name of the first thing
                # said in it. "chat 4" tells nobody which tab held the migration conversation, and
                # a person with seven tabs open is reading the names rather than counting.
                if _is_unnamed(thread.subject):
                    await store.rename_thread(thread.id, inbox.fallback_summary(text) or "a chat")
                return thread
    return await store.create_thread(text[:60] or "untitled")


# How many messages a chat is allowed to have before its name is worth rewriting. The first line
# names it well enough most of the time; it is the conversation that started with "привет" and is
# now about the parser that needs a second look.
RENAME_AFTER = 4


async def rename_if_it_has_moved_on(store: Store, thread: Thread) -> None:
    """Give a chat a name that follows the conversation (docs/11-the-plan.md).

    "Автоматическое название, зависимое от контекста, для названий вкладок чатов" — and the part
    that was missing is that it never changed. A chat took the first thing said in it and kept
    that name for ever, so one that opened with a greeting and turned into a week of work on the
    parser was still called after the greeting.

    Rewritten from what the chat has actually been about, and only:

    - once it has enough in it to be about something (`RENAME_AFTER`),
    - and once, so a long conversation is not renamed on every message — that would make the tab
      bar move under somebody's hand while they were reading it.

    There is no third condition today because there is no way to rename a chat by hand: every name
    here was chosen by this program. When a rename field appears, `renamed_at` is the flag to
    check — a name a person typed is somebody saying what this is, and a model does not get to
    disagree with it.
    """
    said = await store.blocks_in_thread(thread.id)
    if len(said) < RENAME_AFTER or thread.renamed_at:
        return
    lines = [block.input.strip() for block in said if block.input.strip()][:12]
    try:
        reply = "".join([chunk async for chunk in session.stream_answer(inbox.name_prompt(lines))])
    except (session.AnswerFailed, OSError):
        return
    name = next((one.strip() for one in reply.splitlines() if one.strip()), "")[:60]
    if name and name.lower() != thread.subject.lower():
        await store.rename_thread(thread.id, name, automatic=True)
        log.info("threads.renamed", thread=thread.id, name=name)


# A chat named by the `+` button rather than by anything said in it.
_UNNAMED = re.compile(r"\Achat( [0-9]+)?\Z", re.IGNORECASE)


def _is_unnamed(subject: str) -> bool:
    return bool(_UNNAMED.match(subject.strip()))


async def _work(
    store: Store,
    block: Block,
    rows: Sequence[BoardRow],
    *,
    classify: bool,
    a_gesture: bool = False,
    about: str = "",
    deep: Sequence[str] = (),
    history: Sequence[str] = (),
    written: Sequence[str] = (),
    surface: Sequence[str] = (),
    on_bench: Sequence[str] = (),
    pointed_at: int = 0,
) -> None:
    """Read what was typed, then do the one thing it asked for.

    Three kinds, three endings: a question is answered, a thought is recorded and says so, and an
    instruction is turned into a message that waits for a click. The one thing none of them does
    is write into a running session (docs/adr/0002).
    """
    try:
        # The chat may have moved on from whatever it was first called (docs/11-the-plan.md).
        # Before the work rather than after it: a failed run should not cost the rename.
        with contextlib.suppress(Exception):
            thread = await store.thread(block.thread_id)
            if thread is not None:
                await rename_if_it_has_moved_on(store, thread)

        # A gesture says what it is by being one. Everything else is read, because somebody typed a
        # sentence and the console has to work out which of nine things it was; a combine was
        # written by the console and is a question about two cards, always.
        kind = (
            "question" if a_gesture else await classifier.kind(block.input, pointed_at=pointed_at)
        )
        if kind == "unsure":
            # "Чем дороже ветка, тем выше должна быть уверенность и тем скорее нужно спросить, а не
            # догадываться." The one branch that does nothing: the block asks which was meant, and
            # nothing runs until somebody presses a choice. Cheap for the console and expensive for
            # the person, which is why it is offered only against the branches that start agents.
            await store.set_block_kind(block.id, "unsure")
            await store.finish_block(
                block.id,
                "I could not tell whether you were asking me something or telling me to start "
                "work. Starting work is the expensive way to be wrong about that, so nothing has "
                "run. Which did you mean?",
            )
            return
        if kind == "idea":
            await record_idea(store, block, rows)
            return
        if kind == "master":
            await _master_request(store, block, rows)
            return
        if kind == "instruction":
            await _prepare_directive(store, block, rows)
            return
        if kind == "drawing":
            await _draw_it(store, block, surface=surface)
            return
        if kind == "showing":
            await _show_them(store, block, rows, on_bench)
            return
        if kind == "running":
            await _run_the_drawing(store, block, rows, on_bench)
            return
        if kind == "handling" and surface:
            await _rearrange(store, block, rows, surface=surface, on_bench=on_bench)
            return
        await _classify_and_answer(
            store,
            block,
            rows,
            classify=classify,
            a_gesture=a_gesture,
            about=about,
            deep=deep,
            history=history,
            written=written,
            surface=surface,
        )
    except asyncio.CancelledError:
        # Cancellation before `answer_block` is entered used to leave the block `queued` with no
        # task behind it: the template offers cancel for queued and retry only for a settled
        # block, and the crash rule deliberately leaves queued alone on restart. It was stuck for
        # good. Deciding the kind is a full headless run, so this window is seconds wide.
        await asyncio.shield(store.cancel_block(block.id))
        raise


async def cards_from_shape(
    store: Store, steps: Sequence[Mapping[str, str]], lines: Sequence[Mapping[str, str]]
) -> list[str]:
    """Turn a read shape into step cards and the lines between them. One place, two callers.

    The other is the route behind the "in words" panel, which did this inline. Two copies of it
    would be two answers to "what does a drawn process become", and the day they differ is the day
    the same description produces two different benches.
    """
    made: dict[int, str] = {}
    for number, one in enumerate(steps, start=1):
        role = one["role"].strip()
        if not roles.is_a_role(role):
            continue
        card = await store.add_step_card(one["label"].strip() or "a step")
        made[number] = card.name
        await store.set_card_role(card.name, role)
        field = telling.words_for(role)
        if field and one.get("words", "").strip():
            await store.set_card_field(card.name, field, one["words"].strip())
    for one in lines:
        if not ties.is_a_kind(one["kind"]):
            continue
        first, second = int(one["from"]), int(one["to"])
        if first in made and second in made:
            await store.tie_cards(
                from_name=made[first], to_name=made[second], kind=one["kind"], says=one["says"]
            )
    return list(made.values())


async def _run_the_drawing(
    store: Store, block: Block, rows: Sequence[BoardRow], on_bench: Sequence[str]
) -> None:
    """Run the drawing on the workbench, against what was typed.

    "Весь запуск и ввод происходит из одного места, с поля ввода. То есть пайплайн получает вход
    не из формы внутри карточки, а из того, что человек написал внизу — и это же поле его
    запускает."

    Both halves of that sentence are here and the second is the reason for the first. A form inside
    a card would make the input part of the shape, edited in place; running the same shape against
    a different input is the whole reason to build one, so the input belongs to the run and arrives
    the way every other request does.

    The refusal is `engine.begin`'s, which is the function the run button also asks — a button that
    is offered and a message that is refused must not disagree about why.
    """
    await store.set_block_kind(block.id, "running")
    if not on_bench:
        await store.finish_block(
            block.id,
            "There is nothing on the workbench to run. Draw a process or put one there, and say "
            "this again with what it should run against.",
        )
        return
    names = list(on_bench)
    cards = await engine.bench_of(store, names)
    if not engine.all_prompts(cards):
        # "Эта ветка дорогая: она поднимает агентов. Значит здесь и нужно правило «чем дороже
        # ветка, тем скорее спросить»: показать, что будет запущено, и дождаться нажатия."
        #
        # A pipeline of prompts is model calls and starts on the spot; a drawing with work in it
        # puts agents in worktrees, and that is not a thing to be started by a sentence the console
        # had to interpret.
        steps = [one for one in cards if one.role in process.STEPS]
        await store.finish_block(
            block.id,
            telling.as_will_run(
                f"This would start {len(steps)} step{'' if len(steps) == 1 else 's'} that do work "
                "in a checkout, not just ask questions. Nothing has started.",
                names,
            ),
        )
        return
    key, cwd = await _where_a_run_goes(store, names, rows)
    made, why = await engine.begin(store, names=names, repo_key=key, cwd=cwd, given=block.input)
    if made is None:
        await store.finish_block(block.id, f"It did not start: {why}")
        return
    await store.finish_block(
        block.id,
        f"Running the {len(names)} cards on the workbench against what you typed. Each step says "
        "what it produced as it finishes.",
    )


# How much of the board is offered when somebody asks for something on it by meaning. A board this
# long is a prompt nobody should pay for twice, and the things past it are reached by their name in
# Ctrl+K, which is the other half of the same feature.
MOST_TO_LOOK_THROUGH = 80


async def _bring_one_over(store: Store, block: Block, rows: Sequence[BoardRow]) -> None:
    """Find what somebody described on the board, and put it on the workbench.

    A cheap branch: nothing is started, and a miss is visible the moment the card lands and is
    taken off with the × it already has. So this is allowed to guess, on the same terms as the
    reading of what a question follows on from — and it answers "none" rather than bringing the
    nearest thing, because a wrong card is a worse answer than no card. They then have to notice
    it is wrong.
    """
    here: list[tuple[str, str]] = []
    for row in rows:
        session = getattr(row, "session", None)
        if session is None:
            continue
        tail = getattr(row, "tail", None)
        title = getattr(tail, "title", "") if tail else ""
        here.append((f"session:{session.session_id}", f"session · {title or session.name}"))
    # The whole pool rather than its newest two hundred: the bound that matters is the one below,
    # which is about how much a model can be asked to look through, and applying a second one here
    # meant "everything" quietly meaning "the recent half" (agent_desk/store/repo.py, `ideas`).
    for idea in await store.ideas():
        if idea.state in ("new", "kept"):
            here.append((f"idea:{idea.id}", f"idea · {idea.summary}"))
    here = here[:MOST_TO_LOOK_THROUGH]
    if not here:
        await store.finish_block(block.id, "There is nothing on the board to bring over yet.")
        return

    which = await classifier.wanted(block.input, [says for _name, says in here])
    if not which:
        await store.finish_block(
            block.id,
            "Nothing on the board matched that. Nothing was brought over — the wrong card is a "
            "worse answer than none, because you would have to notice it was wrong.",
        )
        return
    names = [here[one - 1][0] for one in which]
    said = "Brought over:\n" + "\n".join(f"- {here[one - 1][1]}" for one in which)
    await store.finish_block(block.id, telling.as_drawn_json(said, names))


async def _where_a_run_goes(
    store: Store, names: Sequence[str], rows: Sequence[BoardRow]
) -> tuple[str, str]:
    """Which project a run happens in: the one the cards are about.

    Read from the ideas on the bench, because that is the only card kind carrying a project a
    person chose. A drawing about nothing in particular has nowhere to run and `engine.begin` says
    so — except for a drawing made only of prompts, which touches nothing and needs nowhere.
    """
    ideas = {f"idea:{one.id}": one for one in await store.ideas()}
    keys = [ideas[name].project_key for name in names if name in ideas and ideas[name].project_key]
    if not keys:
        return ("", "")
    where = next(
        (row.session.cwd for row in rows if getattr(row, "project_key", "") == keys[0]), ""
    )
    return (keys[0] or "", where)


async def _show_them(
    store: Store, block: Block, rows: Sequence[BoardRow], on_bench: Sequence[str]
) -> None:
    """Put things that already exist somewhere on the workbench, because somebody asked for them.

    "И способ попросить: «покажи тикеты из спринта», «покажи открытые PR-ы»."

    Everything else that reaches the bench got there by being dragged or by an answer that drew it.
    This composes nothing and decides nothing: a list is read from the place that has it, each row
    becomes a card, and the block says which list it read and how many rows it found.

    Read fresh rather than shown from the store, because "покажи" is asked when somebody wants to
    know what is there *now*, and a cache with nothing saying how old it is answers a different
    question. Nothing is queued and nothing is written back — the tickets that arrive here are not
    put in this console's queue, which is a decision `autostart.pull_tickets` makes deliberately
    and not a side effect of looking (docs/adr/0010).
    """
    await store.set_block_kind(block.id, "showing")
    what = showing.what_to_show(block.input)
    if not what:
        # Not a list to fetch, so it is something already on the board: "принеси сюда сессию,
        # которая чинит парсер". Found by meaning rather than by label, which is what somebody has
        # when they cannot remember what a session called itself (01M1Z9ZZTPYYK3ER7SPSHHJJQ2).
        await _bring_one_over(store, block, rows)
        return
    key = _which_project(rows, on_bench)
    if not key:
        await store.finish_block(
            block.id,
            "I do not know whose board to read. Put the project on the workbench and ask again — "
            "there is more than one here, and reading the wrong one is worse than asking.",
        )
        return
    found, why = await (
        _read_pulls(store, key) if what == "pulls" else read_tickets_now(store, key)
    )
    if why:
        await store.finish_block(block.id, why)
        return
    if not found:
        await store.finish_block(block.id, f"Nothing there: {showing.says(what)} came back empty.")
        return
    said = f"{len(found)} of {showing.says(what)}, read just now:\n" + "\n".join(
        f"- {name.rpartition('::')[2]}" for name in found
    )
    await store.finish_block(block.id, telling.as_drawn_json(said, found))


def _which_project(rows: Sequence[BoardRow], on_bench: Sequence[str]) -> str:
    """Whose board to read: the project on the workbench, or the only one there is.

    A card on the bench is what somebody is pointing at, and pointing is how everything else in
    this console says which thing it means. Deliberately not "the project whose name appears in the
    sentence": a project key is a URL, nobody types one, and matching a name out of a line is a
    guess that reads somebody else's board with somebody else's credential.

    Nothing is a real answer. Reading the wrong board is worse than asking which one.
    """
    for name in on_bench:
        kind, _, key = name.partition(":")
        if kind == "project" and key:
            return key
    keys = {row.project_key for row in rows if row.project_key}
    return keys.pop() if len(keys) == 1 else ""


async def _read_pulls(store: Store, key: str) -> tuple[list[str], str]:
    """This project's open pull requests, read now and kept (052). Card names, or why not."""
    for link in await store.links(key):
        if not link.token_env:
            continue
        repo = github.repo_of(link.url)
        if not repo:
            continue
        read = await asyncio.to_thread(github.open_pulls, repo, link.token_env)
        if not read.ok:
            return [], f"I could not read the pull requests: {read.detail}"
        await store.replace_pulls(
            key,
            [
                Pull(
                    repo_key=key,
                    number=one.number,
                    title=one.title,
                    url=one.url,
                    waiting_for=one.waiting_for,
                    draft=one.draft,
                    seen_at=0,
                )
                for one in read.pulls
            ],
        )
        return [f"pull:{key}::{one.key}" for one in read.pulls], ""
    return [], (
        "That project has no GitHub link with a credential named on it, so there is nothing here "
        "to read pull requests with. Its settings page is where that is said."
    )


async def read_tickets_now(store: Store, key: str) -> tuple[list[str], str]:
    """This project's board, read now and kept (053). Card names, or why not."""
    for link in await store.links(key):
        where = jira.destination_of(link.url, link.token_env)
        if where is None:
            continue
        read = await asyncio.to_thread(jira.read_board, where)
        if not read.ok:
            return [], f"I could not read the board: {read.detail}"
        await store.replace_tickets(
            key,
            [
                BoardTicket(
                    repo_key=key,
                    key=one.key,
                    summary=one.summary,
                    status=one.status,
                    blocked_by=one.blocked_by,
                    seen_at=0,
                )
                for one in read.tickets
            ],
        )
        # What the board says is related to what, kept with the tickets it belongs to (054).
        await store.replace_ticket_links(
            key,
            [
                TicketLink(repo_key=key, key=one.key, says=link.says, other=link.key)
                for one in read.tickets
                for link in one.links
            ],
        )
        return [f"ticket:{key}::{one.key}" for one in read.tickets], ""
    return [], (
        "That project has no board link with a credential named on it, so there is nothing here "
        "to read tickets from. Its settings page is where that is said."
    )


async def _draw_it(store: Store, block: Block, *, surface: Sequence[str] = ()) -> None:
    """A process described in the input field, drawn as cards on the workbench.

    "Нарисуй процесс релиза: сначала тесты, если красные — чиним."

    Every part of this already existed — `telling.shape_prompt` turns a description into steps and
    lines, and the workbench has put those on the bench since 038 — behind a panel somebody had to
    open first. This is the same act asked for in the field, which is where the rest of the console
    is asked for things.

    The cheapest of the new branches: one model call, cards at the end of it, undone in one press.
    That is why it may be decided on the balance of it where `do` may not.
    """
    await store.set_block_kind(block.id, "drawing")
    try:
        reply = "".join(
            [
                chunk
                async for chunk in session.stream_answer(telling.shape_prompt(block.input, surface))
            ]
        )
    except (session.AnswerFailed, OSError) as exc:
        await store.fail_block(block.id, str(exc))
        return
    # "Рисовать по тому, что модель ВИДИТ… а не по тому, что она помнит про типичные БД." Read
    # before the shape, because a reply that says both is a reply that drew from memory anyway.
    if (needed := telling.read_cannot(reply)) and not telling.read_shape(reply)[0]:
        await store.finish_block(
            block.id,
            f"I can only draw what is in front of me, and that is not: {needed}. Put it on the "
            "workbench — a file, a folder, an answer that describes it — and ask again.",
        )
        return
    steps, lines = telling.read_shape(reply)
    if not steps:
        # A description a model answered with a paragraph about, rather than a shape. Nothing is
        # put on the bench, and saying so beats putting a guess there (agent_desk/telling.py).
        await store.finish_block(
            block.id,
            "That reads like a process, but I could not turn it into steps. Say it as a sequence "
            "— first this, then that, and if it fails, this — and I will draw it.",
        )
        return
    names = await cards_from_shape(store, steps, lines)
    if not names:
        await store.finish_block(
            block.id,
            "That reads like a process, but none of the steps it came back with were a kind of "
            "card this console has. Nothing was put on the workbench.",
        )
        return
    await store.finish_block(block.id, telling.as_drawn_json(telling.as_drawn(steps, lines), names))


async def _rearrange(
    store: Store,
    block: Block,
    rows: Sequence[BoardRow],
    *,
    surface: Sequence[str],
    on_bench: Sequence[str],
) -> None:
    """A request that changes the cards in front of somebody, rather than adding one.

    "Отличие от всего предыдущего в одном: результат запроса — это не новая карточка и не текст, а
    изменение того, что уже лежит."

    The answer is stored as the actions themselves, because that is what the page applies and what
    the block has to be able to show afterwards. What it is *not* is a paragraph: this branch is
    the one where a model's prose would be unusable, and reading it strictly is what keeps a
    rearrangement from being assembled out of a sentence nobody meant as an instruction
    (agent_desk/handling.py).

    "Ничего не запускается, ничего не пишется, ничего не стоит, кроме одного вызова модели" — so a
    reply that cannot be read costs one press of undo and a line saying so, which is why this
    branch is allowed to guess where others are not.
    """
    prompt = session.build_prompt(
        block.input,
        board=board_lines(rows),
        history=[],
        workbench=[*surface, "", handling.what_to_do(on_bench)],
    )
    await store.set_block_kind(block.id, "handling")
    try:
        reply = "".join([chunk async for chunk in session.stream_answer(prompt)])
    except (session.AnswerFailed, OSError) as exc:
        await store.fail_block(block.id, str(exc))
        return
    asked = handling.read(reply, on_bench)
    if asked.empty:
        await store.finish_block(
            block.id,
            "That looked like a request to rearrange the workbench, but the answer did not name "
            "any cards. Nothing was changed.",
        )
        return
    await _write_what_was_asked(store, block, asked)
    await store.finish_block(block.id, handling.as_json(asked))


async def _write_what_was_asked(store: Store, block: Block, asked: handling.Handling) -> None:
    """The three actions whose result is a row rather than a place on a surface (01M23NMJM7ZJYC309B7MWFDGF4).

    Marks, folds and sides live on the page; a line, a name and a role are facts about cards and
    live in the store. They are written here rather than by the page for the reason every other
    write is: the page applies an arrangement once and a card dragged to another bench takes its
    role and its lines with it, which a page-only change would not survive.

    Each goes through the function the mouse already uses, so a line drawn by a sentence and one
    drawn by hand are the same row — including `tie_cards`' own refusal to tie a card to itself,
    and including the undo step it records.
    """
    for line in asked.joined:
        await store.tie_cards(
            from_name=line.from_name,
            to_name=line.to_name,
            kind=line.kind,
            says=line.says,
            thread_id=block.thread_id,
        )
    for made in asked.given:
        await store.set_card_role(made.name, made.role)
    for called in asked.named:
        kind, _, card_id = called.name.partition(":")
        # Only a card this console made. Renaming a session card would be renaming somebody's
        # session, which is a fact about their machine rather than about this bench.
        if kind == "step" and called.label:
            await store.name_step_card(card_id, called.label)


def project_of(rows: Sequence[BoardRow]) -> str:
    """Which project a thought or a request is about, when nothing says otherwise.

    The cards that were on the workbench, if there were any; otherwise this console's own project.
    A thought typed with nothing in front of it is a thought about the thing in front of you, and
    the thing in front of you is the desk (docs/05-ideas.md).
    """
    for row in rows:
        if row.project_key:
            return row.project_key
    return desk_key()


def desk_key() -> str:
    """This console's own project, as a repository key."""
    return f"desk:{own_checkout()}"


async def record_idea(
    store: Store, block: Block, rows: Sequence[BoardRow], *, say: str = ""
) -> None:
    """A thought, recognised as one: recorded, said so, and never asked a second question.

    docs/05-ideas.md is explicit that capture ends here. This run has already read the message
    once to decide it was an idea, so it takes it apart itself rather than handing that to another
    task — but the idea is written down first, before anything else can fail.

    `say` is what the block answers with, because a block is settled **once**. The caller that
    wanted a sentence of its own used to record the idea and then settle the block a second time
    with its text — and between those two writes the block was answered and saying nothing. A test
    caught it by reading the block quickly enough; a person would have seen an answer appear blank
    and then fill in, and a page pushed in that window renders the empty one.
    """
    source_kind, source_ref, context = _capture_context(rows)
    await store.set_block_kind(block.id, "idea")
    idea = await inbox.capture(
        store,
        block.input,
        source_kind=source_kind,  # type: ignore[arg-type]
        source_ref=source_ref,
        context=context,
        block_id=block.id,
        project_key=project_of(rows),
    )
    await store.finish_block(block.id, say)
    await _write_ideas(store, block, idea, rows)


async def _seat_taken(store: Store, repo_key: str) -> bool:
    """Is an agent this program started already working in that project?

    Read from the queue, which is where every start is recorded. A task whose agent has finished
    is settled by the loop in `autostart`, so a stale one costs a wait rather than a second agent.
    """
    return any(
        task.started_at is not None and task.failed_at is None and task.finished_at is None
        for task in await store.tasks(repo_key=repo_key)
    )


async def _pinned_ideas(store: Store, block: Block) -> list[Idea]:
    """The ideas already linked to this message because a human dropped their cards in.

    Written at submission from the targets the field carried, so this is not a guess: it is what
    somebody put in front of the question.
    """
    linked = (await store.ideas_of_blocks()).get(block.id, [])
    known = {idea.id: idea for idea in await store.ideas()}
    return [known[one] for one in linked if one in known]


async def _note_related_ideas(store: Store, block: Block) -> None:
    """Say which written-down thoughts this request is about, if it is about any.

    A guess by a short run, recorded so the console can offer a button — never acted on. The
    ideas it names are live ones only: a thought already built or discarded is not something to
    offer to build again (docs/05-ideas.md).
    """
    live = [idea for idea in await store.ideas() if idea.state in ("new", "kept", "promoted")][:40]
    if not live:
        return
    chosen = await classifier.related(block.input, [idea.summary for idea in live])
    if chosen:
        await store.link_block_ideas(block.id, [live[index - 1].id for index in chosen])


def _session_lines(rows: Sequence[BoardRow]) -> list[str]:
    """The sessions, numbered, for a reply that has to name one of them."""
    return [
        f"{index}. {row.session.name} — {row.session.project} · {row.session.status}"
        f' · "{(row.tail.title if row.tail else None) or "no title read"}"'
        for index, row in enumerate(rows, start=1)
    ]


async def _take_it_on(
    store: Store,
    block: Block,
    rows: Sequence[BoardRow],
    ideas: Sequence[Idea] = (),
    *,
    row: BoardRow | None = None,
    message: str = "",
    directive_id: str = "",
) -> bool:
    """Say what should happen, and it happens (docs/adr/0006).

    An instruction starts an agent. It does not produce a message somebody has to carry by hand:
    that path ended at a wall — the CLI publishes no way into a session that is already running —
    and a console whose answer to "do this" is "copy this" has not done the thing it was asked.

    The trigger is a sentence a person typed. Not a schedule, not an idle agent, not a ticket
    appearing; those are docs/adr/0007's subject and have their own limits. What the agent is told
    is the request, the ideas it was pointed at as they were written, and where it is — verbatim,
    because the summaries are for scanning and the work is built from what was actually said.
    """
    row = row or (rows[0] if rows else None)
    if row is None:
        return False
    return await _start_work(
        store,
        block,
        ideas,
        message=message,
        repo_key=row.project_key or row.session.cwd,
        cwd=row.session.cwd,
        project=row.project_name or row.session.project,
        branch=(row.tail.git_branch if row.tail else "") or "",
        directive_id=directive_id,
    )


async def _start_work(
    store: Store,
    block: Block,
    ideas: Sequence[Idea] = (),
    *,
    message: str = "",
    repo_key: str,
    cwd: str,
    project: str,
    branch: str = "",
    extra: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
    given: Sequence[str] = (),
    directive_id: str = "",
) -> bool:
    """Queue the work and start it, or say why it is waiting. One place, two callers.

    The second caller is a request about this console itself, whose checkout is not a row on the
    board: the desk watches other people's repositories, and its own is simply where it is
    installed (docs/04-threads-and-blocks.md).

    `directive_id` is the message this work was started from, marked as dispatched *before* the
    block settles. Marked afterwards, by the caller, there was a window in which the block said
    "answered" and the message beside it still said nobody had taken it — and a page rendered in
    that window shows exactly that. A block is settled once everything about it is written down,
    which is the same rule `record_idea` was fixed under.
    """
    parts = [message.strip() or block.input]
    if ideas:
        parts += ["The ideas this is about, as they were written down:"]
        parts += [f"- {idea.text}" for idea in ideas]
    if extra:
        parts += ["\n".join(extra)]
    instruction = "\n\n".join(parts)
    task = await store.queue_task(
        repo_key=repo_key,
        cwd=cwd,
        title=block.input[:60],
        instruction=instruction,
        source_kind="idea" if ideas else "instruction",
        # What gets marked built when this agent is gone from the registry.
        source_ref=",".join(idea.id for idea in ideas),
        block_id=block.id,
    )
    # Somebody else is already in that repository on this program's behalf. Two agents in two
    # worktrees of one project, started a minute apart, is the mess docs/adr/0007 is careful
    # about — so this one waits for the seat rather than taking a second one. It is a real,
    # written-down piece of work in the queue, and the console says it is waiting rather than
    # pretending it was done.
    if await _seat_taken(store, repo_key):
        armed = (await store.autostart(repo_key)).armed
        await store.finish_block(
            block.id,
            f"Understood, and it is waiting: something is already running in {project}. "
            + (
                "It starts by itself when that finishes."
                if armed
                else "Start it from the project's page when you want it, or let the project start "
                "its own queue."
            ),
        )
        return True

    await store.take_next_task(repo_key)
    log.info("dispatching an instruction", block=block.id, project=project)
    result = await asyncio.to_thread(
        functools.partial(
            dispatch.start,
            dispatch.build_task(instruction, project=project, branch=branch, secrets=sorted(given)),
            cwd=cwd,
            name=block.input[:40],
            env=env,
        )
    )
    if not result.started:
        await store.task_failed(task.id, result.detail)
        await store.finish_block(
            block.id,
            f"I could not start an agent on it: {result.detail}. Nothing has changed, and the "
            "message is below to send by hand if you want it now.",
        )
        return True

    await store.task_started(task.id, result.agent_id)
    if directive_id and result.agent_id:
        await store.mark_directive_dispatched(directive_id, result.agent_id)
    about = f"{len(ideas)} idea{'' if len(ideas) == 1 else 's'}" if ideas else "it"
    handed = f" It was given {', '.join(given)}." if given else ""
    await store.finish_block(
        block.id,
        f"On it — an agent is working on {about} in {project}, in a worktree of its own "
        f"({result.agent_id}). It is on the board while it runs"
        + (". They leave the list when it finishes." if ideas else ".")
        + handed,
    )
    return True


def own_checkout() -> Path:
    """Where this console's own code is, which is where a request about it has to be done.

    Not a row on the board: the desk watches other people's repositories and does not watch
    itself. This is the package's own directory, which is the checkout when it was started from
    one and an installed copy otherwise — and the difference decides what a `desk` request can do.
    """
    return Path(__file__).resolve().parents[2]


async def briefing(store: Store) -> list[str]:
    """What this console knows, for an agent asked to work on the console's own things.

    "Write documentation for all the ideas" cannot be done by an agent that has to guess what the
    ideas are, and handing it the database would be handing it a file it has no business opening.
    So the facts travel in the prompt: the thoughts, which project each is about, and what is in
    the queue. It is what the console would say out loud if asked.
    """
    ideas = [idea for idea in await store.ideas() if idea.state not in ("dropped", "done")]
    if not ideas:
        return []

    by_project: dict[str, list[str]] = {}
    for idea in reversed(ideas):
        line = f"- {idea.text}" + (" (part of a group)" if idea.parent_id else "")
        by_project.setdefault(idea.project_key or "no project named", []).append(line)

    lines = ["", "## What is written down, by project"]
    for project, thoughts in by_project.items():
        lines += ["", f"### {project}", *thoughts]

    waiting = [task for task in await store.tasks() if task.waiting]
    if waiting:
        lines += ["", "## Work already queued", *[f"- {task.title}" for task in waiting]]
    return lines


async def _secrets_for(store: Store, repo_keys: Sequence[str]) -> dict[str, str]:
    """The tokens these projects named, for the child process that needs them.

    Named, set, and belonging to the work: a project's link says which variable its token is
    under, and this reads the value from where it is kept. Nothing else is passed, and the console
    says which ones were (agent_desk/secrets.py).
    """
    from agent_desk import secrets as kept

    found: dict[str, str] = {}
    for link in await store.links():
        if repo_keys and link.repo_key not in repo_keys:
            continue
        if link.token_env and kept.has(link.token_env):
            found[link.token_env] = kept.get(link.token_env)
    return found


async def _master_request(store: Store, block: Block, rows: Sequence[BoardRow]) -> None:
    """A request about this console: "tidy up the ideas", "put a button here".

    Where the console is running from its own checkout, an agent is started there and does it —
    the same dispatch as any other instruction, addressed at the one repository this program is
    allowed to change. Where it is not — an installed copy with no source beside it — there is
    nothing to start, so the request is written down as a thought about the service and says so.
    That is not a fob-off: it is the only honest answer when the code is somewhere else
    (docs/04-threads-and-blocks.md).
    """
    await store.set_block_kind(block.id, "master")
    await store.set_block_running(block.id)

    here = own_checkout()
    if (here / ".git").exists():
        # A request about the desk is a request about the desk's own things, so it goes with the
        # facts — every thought and which project it belongs to — and with the tokens the projects
        # named, because "collect the blockers from Jira" cannot be done without one.
        given = await _secrets_for(store, [])
        if await _start_work(
            store,
            block,
            repo_key=desk_key(),
            cwd=str(here),
            project=here.name,
            extra=await briefing(store),
            env=given,
            given=sorted(given),
        ):
            return

    await record_idea(
        store,
        block,
        rows,
        say="This is about the console itself, and its code is not on this machine to change — "
        "written down as a thought about the service instead. We will try to take it into account.",
    )


async def _prepare_directive(store: Store, block: Block, rows: Sequence[BoardRow]) -> None:
    """An instruction: taken on where somebody pointed at the work, written out where they did not.

    "Tell Biba to test it again" with nothing dropped in produces a message and a button, because
    nothing can be written into a running session and this program will not guess what to start
    (docs/adr/0002). The same words *with ideas dropped into the output* are a person naming the
    work and saying to do it, and that starts an agent (docs/adr/0006).
    """
    await store.set_block_kind(block.id, "instruction")
    await store.set_block_running(block.id)

    pinned = [idea for idea in await _pinned_ideas(store, block) if idea.state != "done"]
    if pinned:
        await store.link_block_ideas(block.id, [idea.id for idea in pinned])
        if await _take_it_on(store, block, rows, pinned):
            return

    await _note_related_ideas(store, block)
    prompt = session.build_prompt_for_directive(block.input, sessions=_session_lines(rows))
    try:
        reply = "".join([chunk async for chunk in session.stream_answer(prompt)])
    except (session.AnswerFailed, OSError) as exc:
        await store.fail_block(block.id, f"the message could not be written: {exc}")
        return

    index, message = session.read_directive(reply, len(rows))
    if index is None or not message.strip():
        # No session named and nothing dropped in: the console does not pick a repository to start
        # work in on its own. That would be a guess with a worktree at the end of it.
        await store.finish_block(
            block.id,
            "Understood, but I could not tell which project this is for. Drop a card into the "
            "workbench, or name it, and I will get it started.",
        )
        return

    row = rows[index - 1]
    # The message is written down whichever way this goes: it is what was asked for, in the words
    # it would have been said in, and a dispatch that fails leaves it there to send by hand.
    await store.record_directive(
        block_id=block.id,
        session_id=row.session.session_id,
        session_name=f"{row.session.project} · {row.session.name}",
        text_=message.strip(),
    )
    directive = next((one for one in await store.directives() if one.block_id == block.id), None)

    # And then it happens. An instruction that ends in a message somebody has to carry by hand is
    # a console that did not do the thing it was asked (docs/adr/0006).
    if await _take_it_on(
        store,
        block,
        rows,
        row=row,
        message=message.strip(),
        directive_id=directive.id if directive is not None else "",
    ):
        return

    await store.finish_block(
        block.id,
        f"Understood — a message to {row.session.project} · {row.session.name} is written and "
        "waiting below. Nothing reaches that session until you send it.",
    )


async def _attached(store: Store, block_ids: Sequence[str]) -> list[tuple[str, str]]:
    """The earlier messages somebody attached to this one, in the order they attached them.

    Nothing is carried by default. Every call to the model is built from exactly what was asked
    for — the question, the cards in the output field, and whichever earlier exchanges were
    attached — which is what makes the cost of a question predictable and its answer explainable
    (docs/04-threads-and-blocks.md).
    """
    attached: list[tuple[str, str]] = []
    for block_id in block_ids:
        earlier = await store.block(block_id)
        if earlier is not None and earlier.answer:
            attached.append((earlier.input, earlier.answer))
    return attached


async def _thread_history(store: Store, thread_id: str, exclude: str) -> list[tuple[str, str]]:
    """The thread's previous questions and answers, for a block that named no attachments.

    This is the path a page with no JavaScript takes, and the one the thread classifier of
    docs/04-threads-and-blocks.md was written for: attaching a follow-up to a subject is only
    worth anything if the subject then travels with it.
    """
    return [
        (block.input, block.answer or "")
        for block in await store.blocks_in_thread(thread_id)
        if block.id != exclude and block.state == "answered" and block.answer
    ]


async def _classify_and_answer(
    store: Store,
    block: Block,
    rows: Sequence[BoardRow],
    *,
    classify: bool,
    a_gesture: bool = False,
    about: str = "",
    deep: Sequence[str] = (),
    history: Sequence[str] = (),
    written: Sequence[str] = (),
    surface: Sequence[str] = (),
) -> None:
    thread_id = block.thread_id
    if classify:
        open_threads = [
            thread for thread in await store.open_threads() if thread.id != block.thread_id
        ]
        chosen = await classifier.classify(block.input, open_threads)
        if chosen is not None:
            await store.move_block(block.id, chosen, set_by="classifier")
            # Only if it is now empty. Two questions submitted together each open a subject, and
            # each classifier can attach to the other's — closing unconditionally left both blocks
            # sitting in closed threads that no control could reach.
            if not await store.blocks_in_thread(block.thread_id):
                await store.close_thread(block.thread_id)
            thread_id = chosen
        else:
            # It ran, and it chose a new subject. Leaving the block marked `human` would take that
            # decision out of the denominator of the correction rate and make a later human
            # override look like somebody re-correcting themselves — the classifier is wrong in
            # both directions, and only one of them was being counted.
            await store.move_block(block.id, block.thread_id, set_by="classifier")

    # Attached beats inherited: a page that could say exactly what to carry said it, and a page
    # that could not gets the thread it was classified into.
    #
    # And a gesture carries none of it. The conversation is not part of "what do these two cards
    # make": by the tenth combine the thread is nine answers long and every one of them travels
    # with the eleventh question, which is the whole cost. The two cards are in the prompt as the
    # workbench, which is what was actually pointed at.
    earlier = (
        []
        if a_gesture
        else await _attached(store, history)
        if history
        else await _thread_history(store, thread_id, exclude=block.id)
    )
    prompt = session.build_prompt(
        block.input,
        board=board_lines(rows),
        history=earlier,
        about=about,
        transcripts=deep,
        notes=written,
        workbench=surface,
    )
    # Before the answer, not after it. "Как только система поймёт, к чему относится вопрос, он
    # центрируется на этот блок… и готовит ответ" — the order is the content of that sentence: a
    # person who can see what the question was taken to be about has time to say "no, not that
    # one" before an answer to the wrong question arrives.
    await _joins_on_to(store, block)
    await _run(store, block, prompt, _add_dirs([row.session for row in rows]))


async def _joins_on_to(store: Store, block: Block) -> None:
    """Read which card on this bench the question follows on from, and write it down (051).

    The candidates are the cards of the enquiry itself — what it started from and every answer so
    far — and not everything on the bench. A question follows on from something that was *said*;
    the sessions and ideas lying beside it are what it is being asked *with*, which the bench
    already draws as its own kind of line.

    Each candidate is offered as the line the card shows, so the reading is made from what the
    person can see. Anything else and a line appears between two cards for a reason nobody
    watching could have worked out.

    It costs a model call, so it is skipped where there is nothing to choose between — which is
    every ordinary bench, and every question asked before an enquiry has been started.
    """
    start = await store.began(block.thread_id)
    cards = [
        card
        for card in await store.bench_cards(block.thread_id)
        if card.kind == "answer" or (card.name == start and card.name)
    ]
    if len(cards) < 2:
        # One card is not a choice: with only the beginning there, everything follows on from it
        # and a model is being asked to agree. With nothing there, there is no enquiry yet.
        return
    which = await classifier.about(block.input, [card.label for card in cards])
    if which:
        # Several names in one column, comma-separated, because a card name is `kind:id` and can
        # hold no comma. A table would be the tidier shape and would buy nothing: this is a reading
        # that is rewritten whole every time it is made, never joined against, and never counted.
        await store.set_block_relates_to(block.id, ",".join(cards[one - 1].name for one in which))


async def _run(store: Store, block: Block, prompt: str, add_dirs: list[Path]) -> None:
    try:
        await session.answer_block(
            store,
            block,
            prompt,
            add_dirs=add_dirs,
            # Scrubbed here because this text never passes through the store, which is where
            # docs/07-security.md puts the filter. The console used to render a running answer
            # verbatim and the identical finished answer redacted — not a view that forgot to
            # call a filter, but a second output path the document did not know existed.
            on_chunk=lambda text: PARTIAL.__setitem__(block.id, scrub(text)),
            # Scrubbed for the same reason the answer is: this is a path or a pattern a model wrote
            # about files it was pointed at, and it never passes through the store, which is where
            # docs/07-security.md puts the filter.
            on_step=lambda step: DOING.__setitem__(block.id, scrub(step)),
        )
    finally:
        PARTIAL.pop(block.id, None)
        DOING.pop(block.id, None)
    await bring_findings_back(store, block)


async def bring_findings_back(store: Store, block: Block) -> list[str]:
    """Turn what a bringing-back button was told into cards on its bench (075).

    «Вернётся с новыми карточками, основанными на полученных данных.» An answer card is a
    paragraph, read whole or not at all; a finding on a card is taken when it is wanted and left
    when it is not.

    Each becomes an idea, which is what the pool is for and what makes a finding survive the chat
    it arrived in. A finding the inbox cannot make a summary of is left out by name rather than
    written down unreadably — the answer itself is still on its own card either way.
    """
    if not block.brings_back:
        return []
    answered = await store.block(block.id)
    if answered is None or answered.state != "answered" or not answered.answer:
        return []
    on_it = await store.bench_cards(block.thread_id)
    bottom = max((card.y for card in on_it), default=0)
    top = max((card.ord for card in on_it), default=-1)
    made = []
    for said in finding.read_findings(answered.answer):
        try:
            made.append(await inbox.capture(store, said, author="desk"))
        except ValueError:
            continue
    if not made:
        return []
    await store.keep_bench(
        [
            *on_it,
            *(
                BenchCard(
                    name=f"idea:{one.id}",
                    kind="idea",
                    card_id=one.id,
                    label=one.summary,
                    x=FOUND_AT_X,
                    y=bottom + FOUND_STEP_Y * (at + 1),
                    shown="hint",
                    spent=False,
                    ord=top + at + 1,
                    came="found by " + (block.input.splitlines()[0][:40] or "a button"),
                    came_at=one.created_at,
                )
                for at, one in enumerate(made)
            ),
        ],
        thread_id=block.thread_id,
    )
    log.info("blocks.found", block=block.id, cards=len(made))
    return [f"idea:{one.id}" for one in made]


# Where a found card lands, and how far below the last one. A workbench somebody arranged is not
# rearranged by an answer arriving: these come in a column of their own, out of the way
# (042-placed-by-hand.sql).
FOUND_AT_X = 40
FOUND_STEP_Y = 96


async def retry(store: Store, block: Block, rows: Sequence[BoardRow]) -> None:
    """A failed block offers retry, and retrying re-runs the same input (docs/04)."""
    await runs.stop(block.id)
    history = await _thread_history(store, block.thread_id, exclude=block.id)
    prompt = session.build_prompt(block.input, board=board_lines(rows), history=history)
    add_dirs = _add_dirs([row.session for row in rows])
    runs.start(block.id, lambda: _run(store, block, prompt, add_dirs))


async def take_it_as(store: Store, block: Block, rows: Sequence[BoardRow], kind: str) -> None:
    """Somebody has said which of the readings it was, so do that one.

    The choices are the branches this console has, minus the one that is a question about the
    question: `unsure` cannot be chosen, because choosing it is what the block is already showing.
    """
    if kind not in ("question", "idea", "instruction", "master"):
        return
    await store.set_block_kind(block.id, kind)  # type: ignore[arg-type]
    # A person pressing one of the kinds is a person saying what this line really was, which is the
    # one thing a measurement of the classifier can be scored against (072). Written here because
    # this is where it is said — and because nothing else in this program can tell a kind somebody
    # chose from one the classifier decided.
    await store.label_block(block.id, kind)  # type: ignore[arg-type]
    await store.set_block_running(block.id)
    if kind == "idea":
        await record_idea(store, block, rows)
        return
    if kind == "master":
        await _master_request(store, block, rows)
        return
    if kind == "instruction":
        await _prepare_directive(store, block, rows)
        return
    await _classify_and_answer(store, block, rows, classify=False)


async def answer_it_instead(store: Store, block: Block, rows: Sequence[BoardRow]) -> list[str]:
    """ "That was not an idea — write it." The correction the other way round, and the one that was
    missing.

    "Напиши мне план" is a plan somebody wants to read, not a wish that the product should have
    plans in it — and taken as an idea it is *silently not done*: what was asked for never gets
    written, and it lands in a list of things to build instead. Of the two directions this
    correction can go, this is the one whose failure is invisible, which is why it needed a button
    of its own rather than a note in a docstring.

    What it removes is only what nobody has touched: `delete_idea` refuses an idea that has been
    kept, drafted or filed, so a thought somebody has since decided is worth doing survives the
    correction. Returns what it could not remove, so the console can say so rather than implying
    the pool is clean.
    """
    left_behind = []
    for idea in await store.ideas():
        if idea.block_id != block.id:
            continue
        await store.delete_idea(idea.id)
        if await store.idea(idea.id) is not None:
            left_behind.append(idea.summary)
    await store.set_block_kind(block.id, "question")
    await retry(store, block, rows)
    return left_behind


async def set_thread(
    store: Store, block: Block, thread_id: str | None, rows: Sequence[BoardRow]
) -> None:
    """The visible, one-click override — move the block, or split it off (docs/04).

    Two things happen besides the move. The click is logged, because the correction rate is the
    number that decides whether the classifier is worth keeping at all (docs/09-roadmap.md) — ids
    only, never the text of the question. And the block re-runs, because a block corrected into
    the right thread was answered against the wrong one.
    """
    alone = len(await store.blocks_in_thread(block.thread_id)) == 1
    if (thread_id is None and alone) or thread_id == block.thread_id:
        # Nothing to do, in both directions of the same control: the select was submitted
        # unchanged, or a block that is already alone in its subject was asked to be split off
        # again. Either would spend a headless run, flip `thread_set_by` away from the classifier
        # and log a correction — quietly corrupting the one number docs/09-roadmap.md says decides
        # whether the classifier should exist.
        return

    target = thread_id
    if target is None:
        split = await store.create_thread(block.input[:60] or "untitled")
        target = split.id

    log.info(
        "thread override",
        block=block.id,
        was=block.thread_id,
        now=target,
        was_set_by=block.thread_set_by,
    )
    await store.move_block(block.id, target, set_by="human")

    moved = await store.block(block.id)
    if moved is not None:
        await retry(store, moved, rows)


async def cancel(store: Store, block_id: str) -> bool:
    """Stop a run, and make sure the block says so.

    The block used to record itself from inside its own task, which is true only once that task
    has taken a step. A task cancelled before its first one never enters the coroutine at all, so
    the write never happened and the block sat `queued` for ever — no run behind it, `retry`
    offered only for settled blocks, and the crash rule deliberately leaving `queued` alone.
    """
    stopped = await runs.stop(block_id)
    block = await store.block(block_id)
    if block is not None and block.state in ("queued", "running"):
        await store.cancel_block(block_id)
    return stopped
