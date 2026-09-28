"""Which sessions exist, in the CLI's own published words: `claude agents --json` (B7).

`~/.claude/sessions/*.json` is internal state (docs/adr/0004); `claude agents --json` is a command
the CLI documents "for scripting". So it decides which sessions are on the board and what their
status is, and the registry files — which carry what the command does not (the liveness proof,
the CLI version, when the status last moved) — fill in the rest.

It is a process, not a file read: a fifth of a second and ~190 MB each time, measured at 2.1.283.
The board redraws every two seconds, so the answer is kept for `agents_poll_seconds` and read
again after. When the command is missing, slow or unreadable, the board falls back to the
registry alone and says so — an empty board would claim nobody is working.
"""

from __future__ import annotations

import json
import subprocess
import time

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_desk.config import settings
from agent_desk.observe.model import RegistryRead

TIMEOUT_SECONDS = 5.0


class Agent(BaseModel):
    """One row of `claude agents --json` (tests/fixtures/claude_agents.json, 2.1.283)."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    kind: str
    session_id: str = Field(alias="sessionId")
    cwd: str = ""
    name: str = ""
    # Interactive rows say `status` (idle, busy, waiting…); background ones say `state`.
    status: str = ""
    state: str = ""
    waiting_for: str = Field(default="", alias="waitingFor")


class AgentsRead(BaseModel):
    """`agents` is None when the command could not be read; `notice` then says why."""

    model_config = ConfigDict(frozen=True)

    agents: list[Agent] | None = None
    notice: str = ""


def parse(output: str) -> AgentsRead:
    try:
        rows = json.loads(output)
        if not isinstance(rows, list):
            raise ValueError("not a list")
        return AgentsRead(agents=[Agent.model_validate(row) for row in rows])
    except (ValueError, ValidationError) as error:
        # json.JSONDecodeError is a ValueError. The message names the shape, never the content.
        return AgentsRead(
            notice=f"`claude agents --json` no longer reads as recorded ({type(error).__name__})"
        )


def _run() -> AgentsRead:
    try:
        done = subprocess.run(  # noqa: S603 — a list, no shell, the binary from settings
            [settings.claude_bin, "agents", "--json"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return AgentsRead(notice=f"{settings.claude_bin} is not installed here")
    except subprocess.TimeoutExpired:
        return AgentsRead(notice=f"`claude agents --json` took longer than {TIMEOUT_SECONDS:.0f} s")
    if done.returncode != 0:
        return AgentsRead(notice=f"`claude agents --json` exited {done.returncode}")
    return parse(done.stdout)


_kept: tuple[float, AgentsRead] | None = None


def read_agents() -> AgentsRead:
    """The CLI's list, at most `agents_poll_seconds` old. Blocking; the board runs it in a thread."""
    global _kept
    now = time.monotonic()
    if _kept is None or now - _kept[0] >= settings.agents_poll_seconds:
        _kept = (now, _run())
    return _kept[1]


def listed(read: RegistryRead, said: AgentsRead) -> RegistryRead:
    """The registry's sessions, as the CLI lists them.

    A registry file for a session the CLI does not list is left off: the command is the published
    answer to "which sessions exist". A session the CLI lists with no registry file is not made up
    from the five fields the command gives — the board would show a row with no liveness proof —
    it is counted in a notice instead. The status is the CLI's word from the command.
    """
    if said.agents is None:
        return RegistryRead(
            sessions=read.sessions,
            notices=[
                *read.notices,
                f"{said.notice} — the board is read from ~/.claude/sessions alone",
            ],
        )
    status = {one.session_id: one.status for one in said.agents if one.kind == "interactive"}
    sessions = [
        one.model_copy(update={"status": status[one.session_id] or one.status})
        for one in read.sessions
        if one.session_id in status
    ]
    unmatched = len(status) - len(sessions)
    notices = list(read.notices)
    if unmatched > 0:
        notices.append(
            f"{unmatched} session{'' if unmatched == 1 else 's'} listed by `claude agents` "
            f"had no registry file to read the rest from, and {'is' if unmatched == 1 else 'are'} "
            "not shown"
        )
    return RegistryRead(sessions=sessions, notices=notices)
