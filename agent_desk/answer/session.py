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

import structlog

from agent_desk.config import settings
from agent_desk.store.redact import scrub
from agent_desk.store.repo import Block, Store

log = structlog.get_logger()

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


def _ended(code: int) -> str:
    """What a finished run's return code says, in the words of the thing that actually happened.

    A negative code is not an exit status. POSIX has a child either exit with a status of its own
    or be terminated by a signal, and Python encodes the second as `-signum` — so "the run exited
    -9" is that encoding shown to somebody who did not write it, and there is no such exit status.
    docs/04-threads-and-blocks.md asks a failed block to say why; a number that is not the kind of
    number it looks like says less than nothing, because it invites a search for exit code 9.

    It is also the shape a failure here most often takes on this machine rather than a rare one:
    the console runs beside the agents it is watching, and the kernel reclaiming memory ends a run
    with SIGKILL. `test_a_run_that_only_reads_files_still_says_something` names it as one of the
    three shapes that outlive the reader fix (01M1ZEN85PA2NYSV70H59ZZFWN), and a run killed under
    the suite's own load reads the same way there as it does on a card.
    """
    if code >= 0:
        return f"the run exited {code}"
    try:
        named = signal.Signals(-code).name
    except ValueError:  # pragma: no cover - a signal number this platform does not name
        named = f"signal {-code}"
    return f"the run was killed ({named})"


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


def argv(*, add_dirs: Sequence[Path] = (), binary: str = "") -> list[str]:
    """The command line. The prompt is deliberately absent from it — it arrives on stdin.

    `binary` names which engine to run and defaults to the configured one. A second engine — a
    model running on this machine — is given the same flags: it is asked the same question in the
    same shape, and anything that had to differ would be a second parser to keep in step.
    """
    command = [
        binary or settings.claude_bin,
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


# What a tool call is, said in words somebody who does not read code would use (docs/06-console.md).
# Only the three tools this engine is allowed at all: a fourth appearing here would mean the
# allowlist above had moved, and the honest thing to show then is the name it actually used.
_DOING = {
    "Read": "reading",
    "Grep": "searching",
    "Glob": "looking for",
}


def _step_of(event: dict[str, object]) -> str:
    """What this event says the run is doing, or an empty string.

    "Длинный ответ, который возникает целиком через сорок секунд, читается как зависание… по ходу
    прогона надо видеть вызовы инструментов."

    A line *about* the run, never part of its answer. The chunks a caller collects are joined into
    what the block says, and a note about reading a file joined into that would be an answer with
    the working shown in the middle of it.

    Read defensively and bounded: this is the CLI's shape, which is not a contract (docs/adr/0004),
    and the argument to a tool is text a model wrote about files it was pointed at.
    """
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = str(block.get("name") or "")
        given = block.get("input")
        what = ""
        if isinstance(given, dict):
            # The one field of each that says what it is about. `file_path` for a read, `pattern`
            # for a search — the rest is how, and how is not what somebody waiting wants.
            for key in ("file_path", "pattern", "path", "query"):
                if given.get(key):
                    what = _shorten(str(given[key]))
                    break
        return f"{_DOING.get(name, name.lower())} {what}".strip()
    return ""


# How much of a path or a pattern is shown. Long enough to recognise a file, short enough that the
# line stays a line — this sits inside a card, not in a log.
STEP_CHARS = 60


def _shorten(said: str) -> str:
    """A path by its last two parts, anything else by its start.

    The end of a path is the half that identifies it; the beginning is `/home/somebody/projects`,
    which is the same on every line and is what pushes the useful half off the edge.
    """
    flat = " ".join(said.split())
    if "/" in flat:
        flat = "/".join(flat.rsplit("/", 2)[-2:])
    return flat if len(flat) <= STEP_CHARS else flat[: STEP_CHARS - 1].rstrip() + "…"


class Tally:
    """What the asking has cost today, and the ceiling it stops at (043-spending.sql).

    "У автозапуска есть бюджет в час на агентов. У вызовов модели нет ничего… Это та вещь,
    отсутствие которой обнаруживается в конце месяца."

    Attached at startup rather than passed in, the same way the run group is (`web/app.py`). Every
    model call in this program goes through `_run` and there are a dozen callers above it; a
    parameter would be a thing each of them has to remember, and the one that forgot would be a
    call that is spent and not counted — which is this feature failing while appearing to work.

    Nothing attached means nothing is counted and nothing is stopped. That is the right behaviour
    for a runner used outside the console — a test, a script — and it is why the two methods here
    answer plainly rather than raising when there is no store.
    """

    def __init__(self) -> None:
        self._store: Store | None = None

    def attach(self, store: Store | None) -> None:
        self._store = store

    async def stop_here(self) -> str:
        """Why this console must not ask anything else today, or an empty string.

        A sentence rather than a boolean, because what somebody needs at this moment is the number,
        the ceiling and the name of the thing that raises it — "the console stops and *says*", not
        the console stops.

        **Counting money must never be able to fail a question.** A ceiling is a fuse, not part of
        the path an answer travels: if the tally cannot be read — a locked database, a store closed
        under a shutdown, a disk that has gone — then the honest thing is to let the question
        through and say so in the log. Raising instead left the block `running` for ever, because
        this is called from inside the run and nothing above it catches anything but `AnswerFailed`.
        That is exactly the state the crash rule exists to prevent, and it was reachable from a
        counter.
        """
        if self._store is None or settings.daily_usd <= 0:
            return ""
        try:
            spent = await self._store.spent_today()
        # Broad on purpose: a fuse that blows the circuit is not a fuse. Whatever the store
        # failed with, the question goes through.
        except Exception as exc:
            log.warning("spend.unreadable", why=str(exc)[:120])
            return ""
        if spent < settings.daily_usd:
            return ""
        return (
            f"the day's budget is spent: ${spent:.2f} of ${settings.daily_usd:.2f}. "
            "AGENT_DESK_DAILY_USD raises it, and 0 switches the ceiling off"
        )

    async def note(self, usd: float) -> None:
        """Record what a run cost. Same rule: an answer that arrived is not thrown away because
        the note about what it cost could not be written."""
        if self._store is None:
            return
        try:
            await self._store.note_spend(usd)
        except Exception as exc:
            log.warning("spend.unrecorded", usd=usd, why=str(exc)[:120])


tally = Tally()


async def _lines(stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
    """Every line the run printed — including the ones the stream is still holding when its pipe
    breaks under it.

    A `StreamReader` raises a stored exception *ahead of* its own buffer: `readuntil` checks
    `self._exception` before it looks for a separator, so a reset that arrives after the answer
    does takes the answer with it. Measured, and it is not a near miss — three complete lines fed
    in, `set_exception`, and iterating the reader yields **none** of them. The end of a stream
    behaves the other way round: `feed_eof` leaves the buffer alone and every line still comes out,
    which is why only this one case needs saying.

    So the reset is turned back into the end of a stream, which is what it actually is: the pipe is
    gone, the transport has already reported it, and nothing further can be fed. What was in the
    buffer is what the run said, and it is an answer.
    """
    try:
        async for raw in stream:
            yield raw
    except ConnectionResetError:
        # `set_exception(None)` is how a reader is told to stop raising; typeshed says a reader is
        # only ever given a real exception, which is true of the callers it was written for.
        #
        # It is only safe with nothing waiting on the stream: `set_exception` hands its argument
        # to a pending waiter, and `Future.set_exception(None)` is a `TypeError`. Here there is
        # none — the exception that brought us into this branch cleared the waiter on its way out
        # — and the line matters because it is the condition a later refactor could take away
        # without noticing. Reading this stream from two places at once is what would do it.
        stream.set_exception(None)  # type: ignore[arg-type]
        stream.feed_eof()
        async for raw in stream:
            yield raw


async def _run(
    prompt: str,
    *,
    add_dirs: Sequence[Path] = (),
    binary: str = "",
    on_cost: Callable[[float], None] | None = None,
    on_step: Callable[[str], None] | None = None,
) -> AsyncIterator[str]:
    """One engine, one question. Yields the answer as it arrives, or raises `AnswerFailed`.

    Cancellation is the caller's to perform and this generator's to survive: the subprocess is
    killed in `finally`, so a cancelled block does not leave a headless Claude running against a
    question nobody is waiting for any more.

    The day's ceiling is checked here rather than in `stream_answer`, and only for the engine that
    costs money. That is not a detail: it means a console out of budget falls through the machinery
    that is already there for an engine being unavailable, and reaches the local model if somebody
    has configured one — which is exactly what a second engine is for. Raised one level up it would
    stop the console with a free model sitting unused beside it.
    """
    if not binary and (why := await tally.stop_here()):
        raise AnswerFailed(why)
    try:
        process = await asyncio.create_subprocess_exec(
            *argv(add_dirs=add_dirs, binary=binary),
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
            f"needs_toolchain: {binary or settings.claude_bin} is not on PATH, so nothing can "
            "answer a block"
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
        #
        # A run that exits before it has read the prompt breaks this pipe, and the write end raises
        # the same `ConnectionResetError` the read end does. It is suppressed for the same reason:
        # a failed write is not evidence of a failed run. What the run said on stdout and what it
        # exited with decide that, and both are still ahead of us — an engine that really did die
        # early prints nothing, and the ordinary "no answer" path already says so. Left uncaught it
        # reached the `OSError` branch and threw away an answer that was sitting in the pipe.
        with contextlib.suppress(ConnectionResetError, BrokenPipeError):
            stdin.write(prompt.encode())
            await stdin.drain()
            stdin.close()

        async with asyncio.timeout(settings.answer_timeout_seconds):
            # A run that exits the moment it has finished printing can close the pipe while it is
            # still being read, and asyncio raises `ConnectionResetError` out of the middle of the
            # loop. That is the end of the stream rather than a failure, and treating it as one
            # threw away an answer that had arrived — so it is handled here rather than left to
            # the `OSError` branch above, which marks the block failed and loses what was said.
            #
            # Suppressing it was not enough, and the difference is the whole of this: the lines
            # the reader was still holding go with the exception unless they are asked for again.
            # `_lines` asks.
            async for raw in _lines(stdout):
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
                    # What it is doing, before what it has said: a turn that only used a tool has
                    # no text in it, and it is exactly those turns that make the silence.
                    if on_step is not None and (step := _step_of(event)):
                        on_step(step)
                    text = _text_of(event)
                    if text:
                        said_something = True
                        yield text
                elif kind == "result":
                    # What it cost, as the run itself reported it — before the error check, because
                    # a run that failed after spending money still spent it. Read defensively: the
                    # shape is the CLI's and nobody promised it (docs/adr/0004), and a cost that
                    # cannot be read is recorded as nothing rather than as a guess.
                    with contextlib.suppress(TypeError, ValueError):
                        spent = float(event.get("total_cost_usd") or 0)
                        await tally.note(spent)
                        # And to whoever asked, so a step can say what it cost rather than only
                        # the day's total being able to (058-what-a-step-cost.sql).
                        if on_cost is not None:
                            on_cost(spent)
                    if event.get("is_error"):
                        raise AnswerFailed(str(event.get("subtype") or "the run reported an error"))
                    result_text = str(event.get("result") or "")

            code = await process.wait()
            if code != 0 and not said_something:
                raise AnswerFailed(f"{_ended(code)}{complaints.summary()}")
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


# What makes a failure worth trying a second engine for. Every one of these is the engine being
# *unavailable* — out of budget, not installed, unreachable — and none of them is an answer.
#
# The distinction is the whole of this feature and it is worth stating plainly: a refusal is an
# answer. It arrives as text, `stream_answer` yields it, nothing raises, and no fallback can
# possibly fire — which is a structural property rather than a rule anybody has to remember, and a
# test asserts it. Routing a declined request to a model that will not decline it is not something
# this program does (docs/08-non-goals.md).
UNAVAILABLE = (
    "the day's budget is spent",
    "rate limit",
    "rate-limit",
    "usage limit",
    "quota",
    "needs_toolchain",
    "no answer within",
    "could not reach",
    "connection",
)


def unavailable(said: str) -> bool:
    """Was that the engine being unavailable, rather than an answer this program did not like?"""
    lowered = said.lower()
    return any(word in lowered for word in UNAVAILABLE)


async def stream_answer(
    prompt: str,
    *,
    add_dirs: Sequence[Path] = (),
    on_step: Callable[[str], None] | None = None,
    engine: str | None = None,
    on_cost: Callable[[float], None] | None = None,
) -> AsyncIterator[str]:
    """Yield the answer as it arrives, or raise `AnswerFailed`.

    Where a second engine is configured — `AGENT_DESK_LOCAL_MODEL_BIN`, a model running on this
    machine — it is tried when the first one turns out to be *unavailable* and has said nothing
    yet. Both conditions matter. Unavailable is out of budget, not installed or unreachable, never
    a refusal; and "said nothing yet" is what makes a retry safe, because an answer that has
    already begun streaming cannot be started again without repeating itself.

    With no second engine configured — which is every install until somebody sets one — this is
    exactly what it was before.
    """
    # One engine, named, when a card asked for one: a harness that quietly fell back to the other
    # would compare a thing with itself and give no sign that it had (agent_desk/engines.py).
    # Otherwise the ordinary list, which is the primary and the fallback where one is configured.
    if engine is not None:
        engines = [engine]
    else:
        engines = [""]
        if settings.local_model_bin:
            engines.append(settings.local_model_bin)

    for index, binary in enumerate(engines):
        last = index == len(engines) - 1
        said_anything = False
        try:
            async for text in _run(
                prompt, add_dirs=add_dirs, binary=binary, on_step=on_step, on_cost=on_cost
            ):
                said_anything = True
                yield text
        except AnswerFailed as exc:
            # A run that has begun answering cannot be retried without repeating itself, and a
            # failure that is not the engine being unavailable is an answer about the question.
            if last or said_anything or not unavailable(str(exc)):
                raise
            log.info("answer.falling_back", to=engines[index + 1], because=str(exc)[:120])
            continue
        return


def workbench_section(cards: Iterable[str]) -> list[str]:
    """The cards themselves, numbered (agent_desk/looking.py).

    Before the thread and before the transcripts, because a question asked with cards in front of
    it is usually a question *about* those cards, and the thing a question is about should not be
    reached by scrolling past everything it is not about.

    A function rather than four lines inside the prompt because something other than the prompt
    now asks for the same text: an agent calling `bench` over MCP is asking for exactly what a
    question carries, and two places writing that heading are two places that drift apart.
    """
    surface = list(cards)
    return ["", "## The workbench", *surface] if surface else []


def carried_section(written: Iterable[str]) -> list[str]:
    """Ideas somebody dropped into the question.

    They are not evidence of anything an agent did — they are what a person thought at some
    point — and the prompt says so.
    """
    said = list(written)
    return ["", "## Ideas the person carried into this question", *said] if said else []


def build_prompt(
    question: str,
    *,
    board: Iterable[str],
    history: Iterable[tuple[str, str]],
    about: str = "",
    transcripts: Iterable[str] = (),
    notes: Iterable[str] = (),
    workbench: Iterable[str] = (),
) -> str:
    """What a block is answered *from* (docs/04-threads-and-blocks.md).

    The board, the workbench, the thread so far, what the question was pointed at, and the
    question. Two instructions matter as much as the evidence.

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

    lines += workbench_section(workbench)

    previous = list(history)
    if previous:
        lines += ["", "## Earlier in this thread"]
        for asked, answered in previous:
            lines += [f"Q: {asked}", f"A: {answered}", ""]

    lines += carried_section(notes)

    read = list(transcripts)
    if read:
        # Asked for card by card, never by default: one line a session is what the board costs,
        # and this is what it costs to read one properly.
        lines += ["", "## The transcripts you were given, in full", *read]

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
    on_step: Callable[[str], None] | None = None,
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
        async for chunk in stream_answer(prompt, add_dirs=add_dirs, on_step=on_step):
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
