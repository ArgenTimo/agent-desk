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

from agent_desk.answer import session
from agent_desk.observe.model import Session
from agent_desk.store.repo import Block, Store

if TYPE_CHECKING:
    from agent_desk.web.routes import BoardRow

# What a running block has said so far. Memory only, and dropped the moment the block finishes:
# the store holds the answer, and a partial answer is a second copy of a thing already redacted
# once (design/02-data-model.md, "What is deliberately not stored").
PARTIAL: dict[str, str] = {}


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
        if self._group is None:  # pragma: no cover - the app always attaches one
            raise RuntimeError("no task group is running")
        task = self._group.create_task(coroutine)
        self._by_block[block_id] = task
        task.add_done_callback(lambda _: self._by_block.pop(block_id, None))

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


async def submit(store: Store, typed: str, rows: Sequence[BoardRow]) -> Block:
    """Accept one line of input and start answering it.

    Slice by slice: everything typed here is a question in a thread of its own. `/idea` capture and
    the classifier that decides "continuation or new subject" are the two pieces that follow, and
    the thread is recorded as set by a human until a classifier exists to claim otherwise.
    """
    text = typed.strip()
    thread = await store.create_thread(text[:60] or "untitled")
    block = await store.create_block(
        thread_id=thread.id, kind="question", input=text, thread_set_by="human"
    )

    prompt = session.build_prompt(text, board=board_lines(rows), history=[])
    runs.start(block.id, _run(store, block, prompt, _add_dirs([row.session for row in rows])))
    return block


async def _run(store: Store, block: Block, prompt: str, add_dirs: list[Path]) -> None:
    try:
        await session.answer_block(
            store,
            block,
            prompt,
            add_dirs=add_dirs,
            on_chunk=lambda text: PARTIAL.__setitem__(block.id, text),
        )
    finally:
        PARTIAL.pop(block.id, None)


async def retry(store: Store, block: Block, rows: Sequence[BoardRow]) -> None:
    """A failed block offers retry, and retrying re-runs the same input (docs/04)."""
    prompt = session.build_prompt(block.input, board=board_lines(rows), history=[])
    runs.start(block.id, _run(store, block, prompt, _add_dirs([row.session for row in rows])))


def cancel(block_id: str) -> bool:
    """Ask a run to stop. The block records itself as cancelled from inside its own task."""
    return runs.cancel(block_id)
