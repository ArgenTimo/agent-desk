"""The types everything downstream sees, and the one judgement made about them.

Nothing outside `observe/` receives a raw line or a raw dict from `~/.claude/`
(design/01-module-layout.md). These models are that boundary: every shape read off disk is
validated here, so a field that moved fails once with a name attached instead of returning `None`
at five call sites (docs/adr/0004).

What is *not* here is as deliberate as what is. The files carry more than this module names, and
what it does not name, this program does not depend on.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

# The CLI version tests/fixtures/ was recorded from. A live session reporting anything else is not
# an error and never a block — it is the advisory banner of docs/adr/0004, and the fixture README
# is the procedure.
RECORDED_CLI_VERSION = "2.1.259"

# docs/03-session-observation.md: written by the session itself, and the only trustworthy
# statement about what it is doing.
KNOWN_STATUSES = ("idle", "busy", "shell")


def now_ms() -> int:
    """Unix milliseconds — what the registry writes, so a comparison needs no conversion."""
    return int(time.time() * 1000)


class Session(BaseModel):
    """One live session, from one `~/.claude/sessions/<pid>.json`."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    pid: int
    # The liveness field. It is in the file for exactly this reason: a pid alone does not survive
    # pid reuse (docs/03-session-observation.md).
    proc_start: str = Field(alias="procStart")
    session_id: str = Field(alias="sessionId")
    cwd: str
    name: str
    kind: str
    version: str
    status: str
    updated_at: int = Field(alias="updatedAt")
    status_updated_at: int = Field(alias="statusUpdatedAt")

    @property
    def project(self) -> str:
        """The directory the session runs in.

        This is the only place a project name comes from. The transcript's directory is a lossy
        transform of `cwd` and cannot be inverted (docs/03-session-observation.md).
        """
        return Path(self.cwd).name or self.cwd


class JobEnd(BaseModel):
    """How one `claude --bg` job ended, from `~/.claude/jobs/<short>/state.json`.

    Four fields out of twenty-odd, and the omissions are the point (this module's docstring): what
    is not named here is not depended on. `state` is the CLI's word — `done`, `failed`, or
    whatever it grows next — and it is passed through rather than mapped, because a value this
    program has not seen before must not silently become one it has.

    `worktree_branch` is read rather than reconstructed from the task's name: the branch the CLI
    actually made is a fact in this file, and deriving it a second time is a second thing to keep
    in step with the CLI's slug rules.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    state: str
    detail: str = ""
    tokens: int | None = None
    worktree_branch: str = Field(default="", alias="worktreeBranch")

    @property
    def failed(self) -> bool:
        return self.state == "failed"

    @property
    def terminal(self) -> bool:
        """Has this job stopped being work in progress?

        Recorded rather than reasoned about: a `--bg` job reads `working` both while it holds a
        turn *and* while it sits at the prompt afterwards, and its process outlives either — so
        "the session is gone from the registry" never becomes true for an agent that succeeds.
        `done` and `failed` are the two values the CLI writes when it is over, and both carry a
        `firstTerminalAt`. Anything else is treated as still going, which is the safe direction:
        a state this program has not seen must not end somebody's task.
        """
        return self.state in ("done", "failed")


class RegistryRead(BaseModel):
    """What one pass over the registry found, including what it could not read.

    `notices` is the visible half of docs/adr/0004: a file that no longer parses, or a CLI version
    the fixtures were not recorded from, is shown on the board rather than logged into a file
    nobody opens. Advisory, never a block.
    """

    model_config = ConfigDict(frozen=True)

    sessions: list[Session] = []
    notices: list[str] = []


class AgentCall(BaseModel):
    """A subagent a session started, seen in its transcript.

    The session farms work out with the `Agent` tool and the tail carries both halves: the call,
    with the type and the one-line description it was given, and the result that says it came
    back. A call whose result has not arrived is still running — as far as this window can see,
    which is the same limit everything else here has (docs/03-session-observation.md).
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    description: str
    finished: bool

    @property
    def running(self) -> bool:
        """As far as this window can see. A call whose result scrolled out of the tail looks like
        one that has not come back, which is the same limit every other reading here has."""
        return not self.finished


class TailEntry(BaseModel):
    """One entry of the main chain, flattened to what a board row can show."""

    model_config = ConfigDict(frozen=True)

    role: str
    text: str
    at: datetime | None = None


class TranscriptTail(BaseModel):
    """The tail of one session's transcript. Read on demand, never copied into a store."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    title: str | None = None
    last_prompt: str | None = None
    git_branch: str | None = None
    entries: list[TailEntry] = []
    agents: list[AgentCall] = []
    # What the session is carrying: the input of its last assistant turn, cache included. It is
    # the number a person means by "how big has this got" — not a bill, and not a total of
    # everything ever spent, which the window this is read from could not see anyway.
    context_tokens: int | None = None

    @property
    def last_entry(self) -> TailEntry | None:
        return self.entries[-1] if self.entries else None

    @property
    def choices(self) -> list[str]:
        """The options its last words offered, if they were a question with a list under them.

        A reading of the text and nothing more: the console renders these as buttons beside a
        field that can say anything, so a wrong reading costs a button nobody presses rather than
        a claim about what the session wants (`choices_in`).
        """
        last = self.last_entry
        if last is None or last.role != "assistant" or not last.text:
            return []
        return choices_in(last.text)


def choices_in(text: str) -> list[str]:
    """The options a session offered, when its last words were a question with a list under them.

    Asked for as "когда в сессии предлагается пройти опросник или выбрать решение — это
    отображается в качестве кнопок здесь". A session that stops on "1. keep it 2. rewrite it"
    is a session waiting on one word, and a person should not have to open a terminal to say it.

    Narrow on purpose, because the failure mode is a button that sends the wrong thing. Only a
    *numbered* list, only when the text before it asks something, only short lines, and never more
    than a handful — a prose paragraph with "1990" in it must not become a button. Everything it
    is unsure about it leaves alone, and the reply field beside the buttons is always there.
    """
    if "?" not in text:
        return []
    found: list[str] = []
    expect = 1
    for line in text.splitlines():
        stripped = line.strip()
        head = f"{expect}."
        if not stripped.startswith((head, f"{expect})")):
            continue
        option = stripped[len(head) :].strip(" )*-—:")
        # A whole paragraph is not a choice, and neither is an empty one.
        if not option or len(option) > 80:
            return []
        found.append(option)
        expect += 1
        if expect > 6:
            break
    # One option is not a choice; a list that never started at 1 is not one either.
    return found if len(found) >= 2 else []


def signed_by(text: str, name: str) -> bool:
    """Does this reply begin with the name the session was told to sign with?

    Generous about how: `biba:`, `**biba**:`, `[biba]`, `biba —`. What is being detected is a
    session that has *stopped* signing, and a strict match would report that every time a model
    put its name in bold.
    """
    if not name:
        return False
    head = text.lstrip().lstrip("*_`[(#> ").lower()
    return head.startswith(name.lower())


def lost_the_canary(text: str, name: str) -> bool:
    """Was this reply expected to carry a signature and did not (023-canary.sql)?

    Only ever asked about a session this console started and told to sign — an unsigned reply from
    anybody else's session means nothing at all, which is why the name has to be looked up before
    this is called rather than guessed from the text.
    """
    return bool(name) and bool(text.strip()) and not signed_by(text, name)


class AttentionHint(BaseModel):
    """An inference, carrying the observation it was made from.

    "This session is waiting for me" is not on disk (docs/03-session-observation.md, "What cannot
    be known"). It is derived from silence, so it travels with `observation` — the thing actually
    seen — and every surface that renders the flag renders that too. A guessed status shown as a
    fact is worse than no status.
    """

    model_config = ConfigDict(frozen=True)

    waiting: bool
    observation: str


def since(then_ms: int, now: int) -> str:
    """A duration in the largest unit that is still exact enough to act on.

    Minute granularity above a minute is deliberate: a board that re-renders because a number
    ticked from 41s to 42s cannot be read, and nothing on it is decided at that resolution.
    """
    seconds = max(0, (now - then_ms) // 1000)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86_400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86_400}d"


def attention_hint(
    session: Session,
    tail: TranscriptTail | None,
    *,
    now: int,
    after_seconds: int,
) -> AttentionHint:
    """`idle`, plus a last entry from the assistant, plus no change for N seconds.

    All three, and never fewer: an idle session whose last entry is the human's is one that was
    interrupted or has already been answered, and a session idle for ten seconds is one that is
    about to be busy again.
    """
    last = tail.last_entry if tail else None
    seen = f"{session.status} {since(session.status_updated_at, now)}"
    seen += f" · last entry: {last.role}" if last else " · no transcript entry read"

    waiting = (
        session.status == "idle"
        and last is not None
        and last.role == "assistant"
        and (now - session.status_updated_at) >= after_seconds * 1000
    )
    return AttentionHint(waiting=waiting, observation=seen)


def triage_rank(session: Session, hint: AttentionHint) -> int:
    """Sort by what the human is deciding, never by `updatedAt` (docs/06-console.md).

    Inferred-waiting first, then working, then idle. `shell` sits with `busy` because both mean the
    session is doing something and is not waiting on anyone. A status this program does not
    recognise sorts above `idle` rather than below it: an unknown state is not evidence of
    quiet, and the board would otherwise hide a session it stopped understanding.
    """
    if hint.waiting:
        return 0
    if session.status in ("busy", "shell"):
        return 1
    if session.status not in KNOWN_STATUSES:
        return 2
    return 3
