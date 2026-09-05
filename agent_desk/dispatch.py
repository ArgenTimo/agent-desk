"""Start an agent to do what somebody wrote down (docs/adr/0006).

The third door out of this program, and it has the same shape as the other two: importable only
from `agent_desk/web/`, opened only by a click, and it does one thing.

What it does *not* do is most of its specification. It does not steer a session that is already
running — there is still no client for that, and a guessed frame lands in the middle of somebody's
work (docs/adr/0002). It does not dispatch on a timer, on an idle session, or on a ticket
appearing: every one of those is a rule that decides when to start work, and this program does not
have that judgement (docs/08-non-goals.md §2). And it never weakens the permission model of the
agent it starts.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_desk.config import settings

# Flags that would hand a dispatched agent the machine. This program does not pass them, from any
# route, under any setting — an agent that cannot ask a human for permission is an agent nobody is
# standing behind (docs/adr/0006). A test asserts the built command against this list.
NEVER: tuple[str, ...] = (
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "--permission-mode=bypassPermissions",
)

# How long the CLI is given to fork the session and print its id. It returns immediately by
# design; this is the guard against it not returning at all.
START_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class Started:
    """What came back. `agent_id` is the short id `claude attach|logs|stop` take."""

    started: bool
    agent_id: str = ""
    detail: str = ""


def argv(instruction: str, *, worktree: str) -> list[str]:
    """The command, as a list, so that a test can read it and a shell never sees it.

    `--bg` returns as soon as the session exists. `-w` gives it a git worktree of its own, which
    is what keeps the work out of the checkout somebody is sitting in (docs/adr/0006). The
    instruction goes on the command line as the prompt, which is where the CLI takes it.
    """
    return [
        settings.claude_bin,
        "--bg",
        "--worktree",
        worktree,
        instruction,
    ]


def build_task(
    instruction: str,
    *,
    project: str = "",
    branch: str = "",
    notes: Sequence[str] = (),
) -> str:
    """What the agent is actually told.

    A dispatched session starts cold in a repository it has never seen, and the difference between
    a useful one and a wasted one is almost entirely this text. Three things go in: what was asked,
    what it is about, and the one fact it cannot find out for itself — that nobody is at the other
    end of it.

    What deliberately does not go in is this program. The agent is working in a repository, under
    that repository's conventions; agent-desk is the thing that typed the message, and knowing
    about it would only invite the agent to report back to something that cannot listen.
    """
    lines = [instruction.strip(), ""]
    where = " · ".join(part for part in (project, branch) if part)
    if where:
        lines += [f"This is in {where}."]
    written = [note for note in notes if note.strip()]
    if written:
        lines += ["", "Context that came with the request:", *written]
    lines += [
        "",
        "Two things about how this arrived. It was dispatched from a console, so you are running "
        "in a git worktree of your own and **cannot be asked anything once you start** — where a "
        "question would normally be asked, make the reasonable choice, write down what you chose, "
        "and carry on. And read the repository's own CLAUDE.md and docs before changing anything: "
        "its conventions are the ones that apply here, not any you were told elsewhere.",
    ]
    return "\n".join(lines)


def _worktree_name(name: str) -> str:
    """A branch-shaped name from whatever a human typed. Bounded, because it becomes a directory."""
    kept = [character if character.isalnum() else "-" for character in name.lower()]
    slug = "".join(kept).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return (slug or "desk-task")[:40]


def _read_id(output: str) -> str:
    """The short id out of `backgrounded · 79586f63`.

    Read from the first line that names one rather than by position: the CLI prints a small help
    block after it, and a format that grows a line is a format this must survive.
    """
    for line in output.splitlines():
        parts = line.split()
        if parts and parts[0] == "backgrounded" and len(parts) >= 3:
            return parts[-1].strip()
    return ""


def start(instruction: str, *, cwd: str, name: str) -> Started:
    """Start one agent on one instruction. Blocking: the caller runs it in a thread.

    Never raises. Every ending is a `Started`, because this is reached from a route that has to
    render something either way.
    """
    if not instruction.strip():
        return Started(False, detail="there is nothing written to send")
    directory = Path(cwd)
    if not directory.is_dir():
        return Started(False, detail=f"{cwd} is not a directory on this machine any more")
    if shutil.which(settings.claude_bin) is None and not Path(settings.claude_bin).exists():
        return Started(False, detail=f"{settings.claude_bin} is not installed here")

    command = argv(instruction, worktree=_worktree_name(name))
    forbidden = [flag for flag in command if flag in NEVER]
    if forbidden:  # pragma: no cover — the argv builder cannot produce one; the check is the rule
        return Started(False, detail=f"refusing to start an agent with {forbidden[0]}")

    try:
        done = subprocess.run(  # noqa: S603 — a list, no shell, and the binary is from settings
            command,
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=START_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Started(False, detail=f"could not start it: {type(exc).__name__}")

    agent_id = _read_id(done.stdout)
    if done.returncode != 0 or not agent_id:
        # The CLI's own words, trimmed. It says useful things — a dirty worktree, a name in use.
        said = (done.stderr or done.stdout).strip().splitlines()
        return Started(False, detail=said[-1][:300] if said else f"exit {done.returncode}")
    return Started(True, agent_id=agent_id)


def stop(agent_id: str) -> Started:
    """Stop one agent this console started. Its conversation is kept; `claude attach` reopens it."""
    try:
        done = subprocess.run(  # noqa: S603
            [settings.claude_bin, "stop", agent_id],
            capture_output=True,
            text=True,
            timeout=START_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Started(False, detail=f"could not stop it: {type(exc).__name__}")
    if done.returncode != 0:
        said = (done.stderr or done.stdout).strip().splitlines()
        return Started(
            False, agent_id=agent_id, detail=said[-1][:300] if said else "it did not stop"
        )
    return Started(True, agent_id=agent_id)
