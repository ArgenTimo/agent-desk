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
from collections.abc import Callable, Coroutine, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from agent_desk import dispatch
from agent_desk.answer import classify as classifier
from agent_desk.answer import session
from agent_desk.ideas import inbox
from agent_desk.observe.model import Session
from agent_desk.store.redact import scrub
from agent_desk.store.repo import Block, DraftKind, Idea, Store, Thread

if TYPE_CHECKING:
    from agent_desk.web.routes import BoardRow

# What a running block has said so far. Memory only, and dropped the moment the block finishes:
# the store holds the answer, and a partial answer is a second copy of a thing already redacted
# once (design/02-data-model.md, "What is deliberately not stored").
PARTIAL: dict[str, str] = {}

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

    def cancel_all(self) -> list[str]:
        """Shutdown ends runs rather than waiting for them, and says which it ended.

        A console that will not stop while three questions are in the air is the shutdown hang
        this project already fixed once, in a different disguise.
        """
        stopped = list(self._by_block)
        for task in list(self._by_block.values()):
            task.cancel()
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
        # always got, and the text it was typed as.
        await _summarise(store, whole)
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
        await inbox.capture(
            store,
            part,
            source_kind=source_kind,  # type: ignore[arg-type]
            source_ref=source_ref,
            context=context,
            block_id=block.id,
            parent_id=whole.id,
        )


async def _summarise(store: Store, idea: Idea) -> None:
    """Replace the fallback line if a run produces a better one. Never fail the capture over it."""
    try:
        parts = [chunk async for chunk in session.stream_answer(inbox.summary_prompt(idea.text))]
    except (session.AnswerFailed, OSError):
        return
    line = next((one for one in "".join(parts).splitlines() if one.strip()), "").strip()
    if line:
        # Only if the fallback is still there. A human editing the card while this run was in
        # flight has said what they want the line to be, and a generated one arriving afterwards
        # does not get to disagree.
        await store.set_idea_summary(idea.id, inbox.fallback_summary(line), only_if=idea.summary)


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

    # The block exists before anything is classified or answered, and the field is free the moment
    # it does. It starts as a question because that is the safe reading of an unread line, and the
    # run corrects it in a second if it was something else.
    thread = await _thread_for(store, thread_id, text)
    block = await store.create_block(
        thread_id=thread.id, kind="question", input=text, thread_set_by="human"
    )
    carried = await _context_lines(store, rows, targets, history)
    if carried:
        await store.set_block_context(block.id, "\n".join(carried))
    dropped_ideas = [_card(target)[1] for target in targets if _card(target)[0] == "idea"]
    if dropped_ideas:
        await store.link_block_ideas(block.id, dropped_ideas)
    aimed, about = aim(rows, project, session, targets)
    deep = transcripts(rows, targets)
    written = await notes(store, targets)
    classify = not forced_new and not thread_id
    runs.start(
        block.id,
        lambda: _work(
            store,
            block,
            aimed,
            classify=classify,
            about=about,
            deep=deep,
            history=list(history),
            written=written,
        ),
    )
    return block


async def notes(store: Store, dropped: Sequence[str]) -> list[str]:
    """The ideas carried into a question, as text rather than as sessions.

    An idea has no board row and no transcript: what it contributes is what somebody wrote down
    and why it was written down then. Dropping one into the output is how "does this still make
    sense given what these two sessions did" gets asked.
    """
    lines: list[str] = []
    for target in dropped:
        kind, ident, _ = _card(target)
        if kind != "idea":
            continue
        idea = await store.idea(ident)
        if idea is not None:
            lines.append(f"- {idea.summary}: {idea.text}")
    return lines


async def _context_lines(
    store: Store,
    rows: Sequence[BoardRow],
    targets: Sequence[str],
    history: Sequence[str],
) -> list[str]:
    """What this question is being sent with, in the words the console used for it.

    Written before the run starts, so that a block that is still answering can already say what it
    was given. "Why did it say that" is a question about the context, and the context was a
    decision somebody made in a second and has already forgotten.
    """
    lines: list[str] = []
    for target in targets:
        kind, ident, deep = _card(target)
        if kind == "idea":
            idea = await store.idea(ident)
            lines.append(f"idea · {idea.summary}" if idea else "idea · no longer in the inbox")
            continue
        found, label = _rows_named(rows, kind, ident)
        if not found:
            lines.append(f"{kind} · no longer on the board")
            continue
        whole = " · whole transcript" if deep else ""
        lines.append(
            f"{kind} · {label} ({len(found)} session{'' if len(found) == 1 else 's'}){whole}"
        )
    for block_id in history:
        earlier = await store.block(block_id)
        if earlier is not None:
            lines.append(f"earlier · {earlier.input[:80]}")
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
                return thread
    return await store.create_thread(text[:60] or "untitled")


async def _work(
    store: Store,
    block: Block,
    rows: Sequence[BoardRow],
    *,
    classify: bool,
    about: str = "",
    deep: Sequence[str] = (),
    history: Sequence[str] = (),
    written: Sequence[str] = (),
) -> None:
    """Read what was typed, then do the one thing it asked for.

    Three kinds, three endings: a question is answered, a thought is recorded and says so, and an
    instruction is turned into a message that waits for a click. The one thing none of them does
    is write into a running session (docs/adr/0002).
    """
    try:
        kind = await classifier.kind(block.input)
        if kind == "idea":
            await _record_idea(store, block, rows)
            return
        if kind == "instruction":
            await _prepare_directive(store, block, rows)
            return
        await _classify_and_answer(
            store,
            block,
            rows,
            classify=classify,
            about=about,
            deep=deep,
            history=history,
            written=written,
        )
    except asyncio.CancelledError:
        # Cancellation before `answer_block` is entered used to leave the block `queued` with no
        # task behind it: the template offers cancel for queued and retry only for a settled
        # block, and the crash rule deliberately leaves queued alone on restart. It was stuck for
        # good. Deciding the kind is a full headless run, so this window is seconds wide.
        await asyncio.shield(store.cancel_block(block.id))
        raise


async def _record_idea(store: Store, block: Block, rows: Sequence[BoardRow]) -> None:
    """A thought, recognised as one: recorded, said so, and never asked a second question.

    docs/05-ideas.md is explicit that capture ends here. This run has already read the message
    once to decide it was an idea, so it takes it apart itself rather than handing that to another
    task — but the idea is written down first, before anything else can fail.
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
    )
    await store.finish_block(block.id, "")
    await _write_ideas(store, block, idea, rows)


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
    store: Store, block: Block, rows: Sequence[BoardRow], ideas: Sequence[Idea]
) -> bool:
    """Drop an idea into the output, say "take it on", and it is taken on (docs/adr/0006).

    The trigger is a sentence a person typed with cards they dropped there themselves — not a
    schedule, not an idle agent, not a ticket appearing. Both halves have to be present: the run
    read this as an instruction *and* the human pointed at the thoughts it is about. One without
    the other prepares a message and waits, which is what it did before.

    What the agent is told is the request and the ideas as they were written, verbatim. The
    summaries are for scanning; what somebody actually wrote is what the work is built from.
    """
    if not ideas or not rows:
        return False

    row = rows[0]
    instruction = "\n\n".join(
        [block.input, "The ideas this is about, as they were written down:"]
        + [f"- {idea.text}" for idea in ideas]
    )
    project = row.project_name or row.session.project
    task = await store.queue_task(
        repo_key=row.project_key or row.session.cwd,
        cwd=row.session.cwd,
        title=block.input[:60],
        instruction=instruction,
        source_kind="idea",
        # What gets marked built when this agent is gone from the registry.
        source_ref=",".join(idea.id for idea in ideas),
    )
    await store.take_next_task(row.project_key or row.session.cwd)
    result = await asyncio.to_thread(
        dispatch.start,
        dispatch.build_task(
            instruction, project=project, branch=(row.tail.git_branch if row.tail else "") or ""
        ),
        cwd=row.session.cwd,
        name=block.input[:40],
    )
    if not result.started:
        await store.task_failed(task.id, result.detail)
        await store.finish_block(
            block.id,
            f"I could not start an agent on it: {result.detail}. The ideas are untouched.",
        )
        return True

    await store.task_started(task.id, result.agent_id)
    await store.finish_block(
        block.id,
        f"On it — an agent is working on {len(ideas)} idea"
        f"{'' if len(ideas) == 1 else 's'} in {project}, in a worktree of its own "
        f"({result.agent_id}). They leave the list when it finishes.",
    )
    return True


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
        await store.finish_block(
            block.id,
            "Understood, but I could not tell which session this is for. Drop its card into this "
            "field, or name it, and I will write the message.",
        )
        return

    row = rows[index - 1]
    await store.record_directive(
        block_id=block.id,
        session_id=row.session.session_id,
        session_name=f"{row.session.project} · {row.session.name}",
        text_=message.strip(),
    )
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
    about: str = "",
    deep: Sequence[str] = (),
    history: Sequence[str] = (),
    written: Sequence[str] = (),
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
    earlier = (
        await _attached(store, history)
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
    )
    await _run(store, block, prompt, _add_dirs([row.session for row in rows]))


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
        )
    finally:
        PARTIAL.pop(block.id, None)


async def retry(store: Store, block: Block, rows: Sequence[BoardRow]) -> None:
    """A failed block offers retry, and retrying re-runs the same input (docs/04)."""
    await runs.stop(block.id)
    history = await _thread_history(store, block.thread_id, exclude=block.id)
    prompt = session.build_prompt(block.input, board=board_lines(rows), history=history)
    add_dirs = _add_dirs([row.session for row in rows])
    runs.start(block.id, lambda: _run(store, block, prompt, add_dirs))


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
