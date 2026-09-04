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
import re
import signal
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from pathlib import Path

from agent_desk.config import settings
from agent_desk.store.redact import scrub
from agent_desk.store.repo import Block, Store

# What a run may do: read. Nothing on this list can change a byte anywhere.
ALLOWED_TOOLS = ("Read", "Grep", "Glob")

# Named again as a denial, because an allowlist that a future flag quietly widens is a rule with
# one lock on it.
DENIED_TOOLS = ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch")

# The credential paths of docs/07-security.md, handed to the run as its own deny rules.
#
# This is not belt-and-braces, it is the belt. That page names `.claude/settings.json` as the
# mechanism — "a rule that lives only in prose is a wish" — and `--restricted` says in its own
# help text that it "ignores user, project and local settings files (managed settings and
# --settings still apply)". So the one process on this machine that reads observed repositories
# with `Read` pre-approved, over every directory `--add-dir` hands it, was the one process those
# deny rules did not reach. `--settings` reaches it.
#
# **The leading `//` is the whole point.** A pattern without it is anchored at the run's working
# directory, and an observed repository does not arrive that way — it arrives through `--add-dir`.
# Measured: with `Read(**/.env)`, a canary inside an added directory came back verbatim and the
# run reported no permission denial at all; the same file inside the run's own cwd was refused.
# The rule was real and it was covering the one place the danger was not.
#
# Both spellings of a home path are listed, the way `.claude/settings.json` lists them, because
# whether `~` expands inside `--settings` is not something this program should be betting on.
DENIED_PATHS = (
    "Read(//**/.env)",
    "Read(//**/.env.*)",
    "Read(//**/.envrc)",
    "Read(//**/*.pem)",
    "Read(//**/id_rsa*)",
    "Read(//**/.netrc)",
    "Read(//**/.git-credentials)",
    "Read(//**/.npmrc)",
    "Read(//**/.pypirc)",
    "Read(//**/.docker/config.json)",
    "Read(//**/.aws/**)",
    "Read(//**/.ssh/**)",
    "Read(//**/.claude/.credentials.json)",
    "Read(//**/.claude/sessions/*.key)",
    "Read(~/.aws/**)",
    "Read(~/.ssh/**)",
    "Read(~/.claude/.credentials.json)",
    "Read(~/.claude/sessions/*.key)",
)


# How long to wait for a killed run to actually be gone before giving up on reaping it. The
# process is dead by then; this bounds the wait on its pipes, not on it.
_REAP_SECONDS = 5.0


class AnswerFailed(RuntimeError):
    """A run that did not produce an answer, with a reason a human can act on."""


class _Tail:
    """The last little of a run's stderr, kept so a failure can say more than its exit code.

    Bounded, because the point of reading this stream is that nobody blocks on it. Scrubbed on the
    way out, because a diagnostic line can quote a path, an environment variable or whatever the
    tool it came from decided to print (docs/07-security.md).
    """

    LIMIT = 2000

    def __init__(self) -> None:
        self._text = ""

    async def drain(self, stream: asyncio.StreamReader) -> None:
        while chunk := await stream.read(4096):
            self._text = (self._text + chunk.decode(errors="replace"))[-self.LIMIT :]

    def summary(self) -> str:
        last = next((line for line in reversed(self._text.splitlines()) if line.strip()), "")
        return f" — {scrub(last.strip())[:200]}" if last.strip() else ""


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


def denials() -> str:
    """The deny rules, as the JSON `--settings` takes."""
    return json.dumps({"permissions": {"deny": list(DENIED_PATHS)}})


def argv(*, add_dirs: Sequence[Path] = ()) -> list[str]:
    """The command line. The prompt is deliberately absent from it — it arrives on stdin."""
    command = [
        settings.claude_bin,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--restricted",
        # `--restricted` turns off the settings files that carry this project's deny rules, so
        # they are handed back here, where they survive it.
        "--settings",
        denials(),
        # The flag `--restricted`'s own help asks for when it says it does not skip MCP servers.
        "--strict-mcp-config",
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
            # A pipe that is actually drained, into a bounded buffer. Discarding it made every
            # failure read "the run exited 3" and nothing else; leaving it undrained made a noisy
            # run deadlock until the timeout and then lie about being silent.
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
    complaints = _Tail()
    try:
        stdin, stdout = process.stdin, process.stdout
        if stdin is None or stdout is None:  # pragma: no cover - both pipes were requested
            raise AnswerFailed("the answer engine started without pipes")

        if process.stderr is not None:
            drain = asyncio.create_task(complaints.drain(process.stderr))
            drain.add_done_callback(lambda task: task.exception())

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
                raise AnswerFailed(f"the run exited {code}{complaints.summary()}")
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


def build_prompt(
    question: str,
    *,
    board: Iterable[str],
    history: Iterable[tuple[str, str]],
    about: str = "",
) -> str:
    """What a block is answered *from* (docs/04-threads-and-blocks.md).

    The board, the thread so far, what the question was pointed at, and the question. Two
    instructions matter as much as the evidence.

    The first is the document's: an answer built from what agents left on disk can be out of date
    or wrong about intent, and where it cannot tell it says so and names the session to look at.

    The second is who is reading. This window is for somebody watching work they are not doing
    themselves, and often for somebody who does not read code at all — an answer that arrives as
    four paragraphs of technical prose has not answered them, it has given them a second thing to
    read. So: two or three sentences, ordinary words, and the answer first.
    """
    lines = [
        "You are answering one question for somebody watching several Claude Code sessions run in",
        "parallel. You cannot talk to those sessions. Everything below was read off disk, so it is",
        "evidence of what they did, never a statement of what they intend.",
        "",
        "## How to answer",
        "- Two or three sentences. Never a list, never a heading, never a code block.",
        "- Ordinary words. Say 'the tests pass' rather than naming the runner; say 'it is waiting",
        "  for you' rather than quoting a status field. Assume the reader does not read code and",
        "  does not want to.",
        "- The answer first, in the first sentence. Any caveat goes after it, or nowhere.",
        "- If the evidence does not settle it, say so plainly in one sentence and name the session",
        "  worth opening a terminal for. Do not guess and do not pad.",
        "",
        "## The sessions on the board right now",
    ]
    lines += list(board) or ["(no live sessions)"]

    if about:
        lines += ["", "## What this question is about", about]

    previous = list(history)
    if previous:
        lines += ["", "## Earlier in this thread"]
        for asked, answered in previous:
            lines += [f"Q: {asked}", f"A: {answered}", ""]

    lines += ["", "## The question", question]
    return "\n".join(lines)


def build_prompt_for_directive(instruction: str, *, sessions: Iterable[str]) -> str:
    """Turn "tell Biba to test it again" into a message, and into which session it is for.

    What comes back is *prepared*, not sent: docs/adr/0002 puts the one write path behind a human
    click, and this run is not a human. The reply is read strictly — a first line naming a session
    by number, then the message — and an unreadable reply produces no session rather than a guess
    at which console to interrupt.
    """
    lines = [
        "Somebody watching several Claude Code sessions has told you to have one of them do",
        "something. Write the message that should be sent to it. You are not sending anything:",
        "a person reads it and clicks send, or does not.",
        "",
        "## How to answer",
        "- The first line is exactly `session: N`, the number of the session below it is for,",
        "  or `session: none` if the instruction does not clearly name one. Nothing else on it.",
        "- Every line after that is the message itself, addressed to that session, in the words",
        "  its developer would use. Two or three sentences at most, no preamble, no sign-off.",
        "- Say what to do, not who asked. The session receiving it has no idea this tool exists.",
        "",
        "## The sessions",
    ]
    listed = list(sessions)
    lines += listed or ["(none are running)"]
    lines += ["", "## What you were told", instruction]
    return "\n".join(lines)


def read_directive(reply: str, count: int) -> tuple[int | None, str]:
    """The session number the reply names and the message under it, or `(None, ...)`.

    Strict on purpose, and in the same shape as the classifier: the first line must be the whole
    decision. A reply that opens with prose has not named a session, and preparing a message to
    the wrong console is exactly the mistake this program is built not to make.
    """
    head, _, rest = reply.strip().partition("\n")
    body = rest.strip()
    match = re.match(r"\Asession:\s*([0-9]{1,2}|none)\Z", head.strip(), re.IGNORECASE)
    if match is None:
        return None, reply.strip()
    chosen = match.group(1).lower()
    if chosen == "none" or not (1 <= int(chosen) <= count):
        return None, body
    return int(chosen), body


async def answer_block(
    store: Store,
    block: Block,
    prompt: str,
    *,
    add_dirs: Sequence[Path] = (),
    on_chunk: Callable[[str], None] | None = None,
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
            if on_chunk is not None:
                # docs/04: the answer as it streams. The partial lives in memory only — a second
                # copy of an answer is a second thing to redact (docs/07-security.md).
                on_chunk("".join(chunks))
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
