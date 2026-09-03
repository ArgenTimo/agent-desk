"""One headless `claude -p` run per block.

It starts its own session and never messages a running one — that path exists once, in `web`,
behind a human click (docs/adr/0002).

Two properties of this module are load-bearing rather than incidental:

**The prompt goes in on stdin, never in argv.** It carries transcript tails, and docs/07-security.md
forbids transcript text in a subprocess argument for the plain reason that `/proc/<pid>/cmdline` is
readable by anyone on the machine — including, with some irony, the board this program draws.

**The run cannot write.** A block's answer is built with read access to the repositories being
observed (docs/04-threads-and-blocks.md), and "never write anything into an observed repository"
is one of the five rules that do not bend. The mechanism is four flags, and they are redundant on
purpose: an allowlist of read-only tools, an explicit denial of the writing ones, restricted mode
which removes the tools that run code at all, and a permission policy that denies anything which
would otherwise have asked a human who is not there.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from collections.abc import AsyncIterator, Iterable, Sequence
from pathlib import Path

from agent_desk.config import settings
from agent_desk.store.repo import Block, Store

# What a run may do: read. Nothing on this list can change a byte anywhere.
ALLOWED_TOOLS = ("Read", "Grep", "Glob")

# Named again as a denial, because an allowlist that a future flag quietly widens is a rule with
# one lock on it.
DENIED_TOOLS = ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch")


# How long to wait for a killed run to actually be gone before giving up on reaping it. The
# process is dead by then; this bounds the wait on its pipes, not on it.
_REAP_SECONDS = 5.0


class AnswerFailed(RuntimeError):
    """A run that did not produce an answer, with a reason a human can act on."""


def _kill_run(process: asyncio.subprocess.Process) -> None:
    """Kill the run, not merely the process that started it.

    `claude` spawns children — tool calls, MCP servers — and they inherit the pipes. Killing only
    the parent leaves them holding stdout open, so `wait()` blocks until the *grandchild* finishes
    on its own: measured at 28 seconds past a 2-second timeout, with the console's task alive the
    whole time and a headless Claude still running against a question nobody is waiting for.
    The run is therefore started in its own session and killed as a group.
    """
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # pragma: no cover - it was already gone
        process.kill()


def argv(*, add_dirs: Sequence[Path] = ()) -> list[str]:
    """The command line. The prompt is deliberately absent from it — it arrives on stdin."""
    command = [
        settings.claude_bin,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--restricted",
        "--permission-prompts",
        "none",
        "--allowedTools",
        *ALLOWED_TOOLS,
        "--disallowedTools",
        *DENIED_TOOLS,
    ]
    for directory in add_dirs:
        command += ["--add-dir", str(directory)]
    return command


def _text_of(event: dict[str, object]) -> str:
    """The assistant text carried by one stream-json event, if it carries any."""
    message = event.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts = []
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


async def stream_answer(
    prompt: str,
    *,
    add_dirs: Sequence[Path] = (),
) -> AsyncIterator[str]:
    """Yield the answer as it arrives, or raise `AnswerFailed`.

    Cancellation is the caller's to perform and this generator's to survive: the subprocess is
    killed in `finally`, so a cancelled block does not leave a headless Claude running against a
    question nobody is waiting for any more.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *argv(add_dirs=add_dirs),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Its own process group, so the whole run can be ended in one call — see _kill_run.
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise AnswerFailed(
            f"needs_toolchain: {settings.claude_bin} is not on PATH, so nothing can answer a block"
        ) from exc

    said_something = False
    result_text = ""
    try:
        stdin, stdout = process.stdin, process.stdout
        if stdin is None or stdout is None:  # pragma: no cover - both pipes were requested
            raise AnswerFailed("the answer engine started without pipes")

        # docs/07-security.md: transcript text never goes into a subprocess argument, and this
        # prompt is made of transcript tails. /proc/<pid>/cmdline is world-readable; stdin is not.
        stdin.write(prompt.encode())
        await stdin.drain()
        stdin.close()

        async with asyncio.timeout(settings.answer_timeout_seconds):
            async for raw in stdout:
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    # The CLI's own format, and it is not a contract either (docs/adr/0004). A
                    # line this program cannot read is skipped rather than raised on: the run may
                    # still answer, and an unreadable line is not evidence that it will not.
                    continue
                if not isinstance(event, dict):
                    continue

                kind = event.get("type")
                if kind == "assistant":
                    text = _text_of(event)
                    if text:
                        said_something = True
                        yield text
                elif kind == "result":
                    if event.get("is_error"):
                        raise AnswerFailed(str(event.get("subtype") or "the run reported an error"))
                    result_text = str(event.get("result") or "")

            code = await process.wait()
            if code != 0 and not said_something:
                raise AnswerFailed(f"the run exited {code}")
            if not said_something and result_text:
                # Nothing streamed, but the run summarised itself. Better than an empty answer,
                # and it is the same text.
                yield result_text
    except TimeoutError as exc:
        raise AnswerFailed(f"no answer within {settings.answer_timeout_seconds:.0f}s") from exc
    finally:
        if process.returncode is None:
            _kill_run(process)
            # Bounded: a pipe held by something outside the group must not become this task's
            # problem, and the run itself is already dead by here.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), _REAP_SECONDS)


def build_prompt(question: str, *, board: Iterable[str], history: Iterable[tuple[str, str]]) -> str:
    """What a block is answered *from* (docs/04-threads-and-blocks.md).

    The board, the thread so far, and the question. The instruction at the end is the one the
    document insists on: an answer built from what agents left on disk can be out of date or wrong
    about intent, and where it cannot tell it says so and names the session to go and look at.
    """
    lines = [
        "You are answering one question for a developer who is watching several Claude Code",
        "sessions run in parallel. You cannot talk to those sessions. Everything below was read",
        "off disk, so it is evidence of what they did, never a statement of what they intend.",
        "",
        "## The sessions on the board right now",
    ]
    lines += list(board) or ["(no live sessions)"]

    previous = list(history)
    if previous:
        lines += ["", "## Earlier in this thread"]
        for asked, answered in previous:
            lines += [f"Q: {asked}", f"A: {answered}", ""]

    lines += [
        "",
        "## The question",
        question,
        "",
        "Answer in a few sentences. Where the evidence does not settle it, say so plainly and",
        "name the session worth opening a terminal for, rather than guessing.",
    ]
    return "\n".join(lines)


async def answer_block(
    store: Store,
    block: Block,
    prompt: str,
    *,
    add_dirs: Sequence[Path] = (),
) -> None:
    """Run one block from `queued` to `answered`, or to `failed` with the reason.

    Every exit is written to the store, which is what lets this be started as a task without
    becoming a failure nobody observes: the task itself never raises except on cancellation, so a
    TaskGroup holding a hundred of these does not tear itself down because one question went
    wrong.
    """
    await store.set_block_running(block.id)
    chunks: list[str] = []
    try:
        async for chunk in stream_answer(prompt, add_dirs=add_dirs):
            chunks.append(chunk)
    except asyncio.CancelledError:
        # Shielded: the cancellation is already in flight, and a state that did not get written
        # would come back as `running` forever — the exact thing the crash rule exists to prevent.
        await asyncio.shield(store.cancel_block(block.id))
        raise
    except AnswerFailed as exc:
        await store.fail_block(block.id, str(exc))
        return
    except OSError as exc:
        await store.fail_block(block.id, f"{type(exc).__name__} while running the answer engine")
        return

    await store.finish_block(block.id, "".join(chunks).strip())
