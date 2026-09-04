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

    @property
    def last_entry(self) -> TailEntry | None:
        return self.entries[-1] if self.entries else None


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
