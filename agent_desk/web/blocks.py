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
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from agent_desk.answer import classify as classifier
from agent_desk.answer import session
from agent_desk.ideas import inbox
from agent_desk.observe.model import Session
from agent_desk.store.redact import scrub
from agent_desk.store.repo import Block, DraftKind, Idea, Store

if TYPE_CHECKING:
    from agent_desk.web.routes import BoardRow

# What a running block has said so far. Memory only, and dropped the moment the block finishes:
# the store holds the answer, and a partial answer is a second copy of a thing already redacted
# once (design/02-data-model.md, "What is deliberately not stored").
PARTIAL: dict[str, str] = {}

# Ideas whose draft is being written, so the inbox can say "drafting" instead of showing a click
# that appeared to do nothing. Memory only, for the same reason as PARTIAL.
DRAFTING: set[str] = set()

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

    def start(self, block_id: str, coroutine: Coroutine[object, object, None]) -> None:
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
            previous.cancel()

        task = self._group.create_task(self._contained(block_id, coroutine))
        self._by_block[block_id] = task
        task.add_done_callback(lambda done: self._forget(block_id, done))

    def _forget(self, block_id: str, done: asyncio.Task[None]) -> None:
        """Only the task that is still the current one may remove itself."""
        if self._by_block.get(block_id) is done:
            del self._by_block[block_id]

    @staticmethod
    async def _contained(block_id: str, coroutine: Coroutine[object, object, None]) -> None:
        try:
            await coroutine
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

    def cancel_all(self) -> None:
        """Shutdown ends runs rather than waiting for them.

        A console that will not stop while three questions are in the air is the shutdown hang
        this project already fixed once, in a different disguise.
        """
        for task in list(self._by_block.values()):
            task.cancel()

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

    The block is `answered` the moment it exists, because it is: the card is the whole content of
    an idea block, and nothing about the thought is pending. What runs afterwards only improves
    the summary line, and the idea is complete without it.
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
    runs.start(f"summary:{idea.id}", _summarise(store, idea))
    return block


async def _summarise(store: Store, idea: Idea) -> None:
    """Replace the fallback line if a run produces a better one. Never fail the capture over it."""
    try:
        parts = [chunk async for chunk in session.stream_answer(inbox.summary_prompt(idea.text))]
    except (session.AnswerFailed, OSError):
        return
    line = next((one for one in "".join(parts).splitlines() if one.strip()), "").strip()
    if line:
        await store.set_idea_summary(idea.id, inbox.fallback_summary(line))


async def draft(store: Store, idea: Idea, kind: DraftKind) -> None:
    """One of the three actions of docs/05-ideas.md. All three produce text in this tool."""
    if kind == "paste":
        await store.create_draft(idea_id=idea.id, kind=kind, body=inbox.paste_body(idea))
        return

    DRAFTING.add(idea.id)
    runs.start(f"draft:{idea.id}:{kind}", _draft(store, idea, kind))


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
        DRAFTING.discard(idea.id)


async def submit(store: Store, typed: str, rows: Sequence[BoardRow]) -> Block:
    """Accept one line of input and start answering it.

    `/idea` captures instead of asking. `/new` forces a new thread, which is what a question gets
    anyway until the classifier of docs/04-threads-and-blocks.md exists to propose otherwise — so
    the thread is recorded as set by a human, because it was.
    """
    text = typed.strip()
    if text.startswith(IDEA_PREFIX):
        return await capture_idea(store, text[len(IDEA_PREFIX) :].strip(), rows)
    if text.startswith(NEW_PREFIX):
        text = text[len(NEW_PREFIX) :].strip()

    # The block exists before anything is classified or answered, and the field is free the moment
    # it does. Its thread starts as the default — a subject of its own — and says so: `human`,
    # because nobody but the person who typed it has decided anything yet.
    forced_new = typed.strip().startswith(NEW_PREFIX)
    thread = await store.create_thread(text[:60] or "untitled")
    block = await store.create_block(
        thread_id=thread.id, kind="question", input=text, thread_set_by="human"
    )
    runs.start(
        block.id,
        _classify_then_run(store, block, rows, classify=not forced_new),
    )
    return block


async def _thread_history(store: Store, thread_id: str, exclude: str) -> list[tuple[str, str]]:
    """The thread's previous questions and answers, which a continuation inherits (docs/04)."""
    return [
        (block.input, block.answer or "")
        for block in await store.blocks_in_thread(thread_id)
        if block.id != exclude and block.state == "answered" and block.answer
    ]


async def _classify_then_run(
    store: Store,
    block: Block,
    rows: Sequence[BoardRow],
    *,
    classify: bool,
) -> None:
    """Decide the subject first, then answer against it.

    The order matters and it is the reason classification is not a separate task: a block attached
    to a thread after its answer was built would have been answered against the wrong background,
    which is the failure the attaching was meant to prevent.
    """
    try:
        await _classify_and_answer(store, block, rows, classify=classify)
    except asyncio.CancelledError:
        # Cancellation before `answer_block` is entered used to leave the block `queued` with no
        # task behind it: the template offers cancel for queued and retry only for a settled
        # block, and the crash rule deliberately leaves queued alone on restart. It was stuck for
        # good. Classification is a full headless run, so this window is seconds wide.
        await asyncio.shield(store.cancel_block(block.id))
        raise


async def _classify_and_answer(
    store: Store,
    block: Block,
    rows: Sequence[BoardRow],
    *,
    classify: bool,
) -> None:
    thread_id = block.thread_id
    if classify:
        open_threads = [
            thread for thread in await store.open_threads() if thread.id != block.thread_id
        ]
        chosen = await classifier.classify(block.input, open_threads)
        if chosen is not None:
            await store.move_block(block.id, chosen, set_by="classifier")
            await store.close_thread(block.thread_id)
            thread_id = chosen

    history = await _thread_history(store, thread_id, exclude=block.id)
    prompt = session.build_prompt(block.input, board=board_lines(rows), history=history)
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
    history = await _thread_history(store, block.thread_id, exclude=block.id)
    prompt = session.build_prompt(block.input, board=board_lines(rows), history=history)
    runs.start(block.id, _run(store, block, prompt, _add_dirs([row.session for row in rows])))


async def set_thread(
    store: Store, block: Block, thread_id: str | None, rows: Sequence[BoardRow]
) -> None:
    """The visible, one-click override — move the block, or split it off (docs/04).

    Two things happen besides the move. The click is logged, because the correction rate is the
    number that decides whether the classifier is worth keeping at all (docs/09-roadmap.md) — ids
    only, never the text of the question. And the block re-runs, because a block corrected into
    the right thread was answered against the wrong one.
    """
    if thread_id is not None and thread_id == block.thread_id:
        # The select was submitted unchanged. Recording that as a human correction would spend a
        # run, flip `thread_set_by` away from the classifier, and quietly corrupt the one number
        # docs/09-roadmap.md says decides whether the classifier should exist.
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


def cancel(block_id: str) -> bool:
    """Ask a run to stop. The block records itself as cancelled from inside its own task."""
    return runs.cancel(block_id)
