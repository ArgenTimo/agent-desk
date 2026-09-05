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

import os
import secrets
import shutil
import subprocess
from collections.abc import Mapping, Sequence
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


def resume_argv(session_id: str, instruction: str) -> list[str]:
    """The command that continues one background session (docs/adr/0009).

    `--bg --resume <session-id>` is the CLI's own door: "continues that session in the background
    under the same ID". The id is the full one from the registry rather than the short one, which
    is what `--resume` takes.
    """
    return [
        settings.claude_bin,
        "--bg",
        "--resume",
        session_id,
        instruction,
    ]


# What the CLI says when the account has nothing left to spend. Matched loosely and on purpose:
# this is the one shape here that was not recorded from a real occurrence, so it is a hint that
# turns a failure into a wait, never a parser anything depends on (docs/adr/0004). When none of
# these appear the failure is an ordinary failure and is counted as one.
LIMIT_SAID = ("rate limit", "rate-limit", "usage limit", "resets at", "try again at", "quota")


def looks_like_a_limit(said: str) -> bool:
    """Is this failure the account being out of budget rather than something being broken?"""
    lowered = said.lower()
    return any(phrase in lowered for phrase in LIMIT_SAID)


def build_task(
    instruction: str,
    *,
    project: str = "",
    branch: str = "",
    notes: Sequence[str] = (),
    secrets: Sequence[str] = (),
    standing: str = "",
    glossary: Sequence[tuple[str, str]] = (),
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
    # What is true in this project whatever the task is: the conventions and the wishes somebody
    # wrote once so they would not have to say them again (020-project-note.sql). Verbatim, and
    # under a heading that says who it came from — an agent has to be able to tell a standing
    # preference from the thing it was asked to do.
    if standing.strip():
        lines += [
            "",
            "What the person who runs this project asked anybody working here to know:",
            standing.strip(),
        ]
    # The words they use for things. An agent dispatched into a project does not have its
    # vocabulary, and today that costs a paragraph in every instruction or a wrong guess
    # (021-glossary.sql).
    if glossary:
        lines += [
            "",
            "Words they use here, and what they mean by them:",
            *[f"- **{term}** — {means}" for term, means in glossary],
        ]
    if secrets:
        lines += [
            "",
            "Credentials you were given, in the environment: " + ", ".join(secrets) + ". Use them "
            "for what was asked and nothing else, and never write one into a file, a commit, a "
            "log line or a message.",
        ]
    lines += [
        "",
        "Two things about how this arrived. It was dispatched from a console, so you are running "
        "in a git worktree of your own and **cannot be asked anything once you start** — where a "
        "question would normally be asked, make the reasonable choice, write down what you chose, "
        "and carry on. And read the repository's own CLAUDE.md and docs before changing anything: "
        "its conventions are the ones that apply here, not any you were told elsewhere.",
    ]
    return "\n".join(lines)


# Names for a new instance, so the field arrives filled in rather than empty. A name matters more
# than it sounds: "biba said the parser is fine" is a sentence somebody can hold in their head, and
# "agent" three times over is three rows nobody can tell apart. Short, sayable, and nothing that
# reads like a status word.
NAMES: tuple[str, ...] = (
    "biba",
    "boba",
    "koda",
    "mira",
    "nix",
    "odo",
    "pim",
    "quill",
    "rue",
    "sable",
    "tolo",
    "umber",
    "vane",
    "wren",
    "yuki",
    "zeph",
    "arlo",
    "bex",
    "cyd",
    "dot",
)


def a_name() -> str:
    """One of them, at random. The field is pre-filled with it and anybody may type over it."""
    return secrets.choice(NAMES)


def introduce(who: str, *, project: str, doing: str = "", env_names: Sequence[str] = ()) -> str:
    """What a new instance is told on its first breath.

    It is a new pair of hands in a repository nobody has introduced it to, so the first thing it
    is asked to do is read — not to produce something. A session that starts by changing files it
    has not read is the reason this text exists at all.
    """
    lines = [
        f"You are {who}, working in {project}. This is a fresh worktree of that repository, made "
        "for you, and you are its only occupant.",
        "",
        "Start by reading, not by changing anything: the repository's CLAUDE.md and its docs, "
        "then enough of the code to know how it is put together. Its conventions are the ones "
        "that apply here.",
    ]
    if doing:
        lines += ["", f"What you are here for: {doing}"]
    if env_names:
        lines += [
            "",
            "The environment this project expects: " + ", ".join(env_names) + ". Check what is "
            "actually set before assuming any of it, and say so if something is missing rather "
            "than working around it.",
        ]
    lines += [
        "",
        "You were started from a console and **cannot be asked anything once you begin** — where "
        "a question would normally be asked, make the reasonable choice, write down what you "
        "chose, and carry on. When you have read enough to be useful, say in a few lines what you "
        "found and what you would do first.",
    ]
    return "\n".join(lines)


def go_looking(project: str) -> str:
    """What an agent is told when it was sent to find its own work (docs/adr/0008).

    Every clause of this is a fence. One thing, because an agent asked to improve a project
    without a bound improves it until its context runs out. Something already there, because
    fixing is maintenance and inventing is design — and design is the human's. A test, because a
    fix nobody can check is a claim. And stop, because the next thing it finds is the next run's.
    """
    return "\n".join(
        [
            f"Nothing is queued for {project}, so you were sent to find one thing worth fixing.",
            "",
            "Find exactly one, of these kinds and no others:",
            "- something that is broken, or wrong at an edge nobody covered",
            "- a behaviour the documentation or a docstring claims and the code no longer does",
            "- a test that is missing where a mistake would be silent",
            "- a dependency with a known advisory, or an obvious vulnerability in this code",
            "- code nothing reaches any more",
            "",
            "Then: make the smallest change that fixes it, prove it with a test that fails without",
            "the change, and run whatever this repository uses as its gate. Stop there — the next",
            "thing you find is the next run's, and a branch with one clear fix in it is worth more",
            "than one with five.",
            "",
            "What you must not do: add a feature, change an interface anybody depends on, rewrite",
            "something that works, or start a redesign. You were not asked to improve the product;",
            "you were asked to fix what is already there. If you find nothing worth a change, say",
            "so and stop — that is a good outcome and it costs nobody anything.",
            "",
            "Write in the commit message what you found and how you know it was real.",
        ]
    )


# Cyrillic to latin, because the person using this console writes in Russian and the CLI does not
# accept a worktree name outside `[A-Za-z0-9._-]` — it exits 1 before the model ever starts, which
# is how six dispatched agents died without spending a token. Transliterating rather than dropping:
# the name becomes a branch and a directory somebody has to recognise later.
CYRILLIC: Mapping[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "і": "i",
    "ї": "yi",
    "є": "ye",
    "ґ": "g",
}


def _worktree_name(name: str) -> str:
    """A branch-shaped name from whatever a human typed. Bounded, because it becomes a directory.

    ASCII by construction, not by hope: `str.isalnum` is true for every letter in every alphabet,
    and the CLI's `--worktree` accepts only letters, digits, dots, underscores and dashes in the
    ASCII sense. Anything it would reject is transliterated where there is a sensible letter for
    it and dropped where there is not.
    """
    kept: list[str] = []
    for character in name.lower():
        if character in CYRILLIC:
            kept.append(CYRILLIC[character])
        elif character.isascii() and character.isalnum():
            kept.append(character)
        else:
            kept.append("-")
    slug = "".join(kept).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return (slug or "desk-task")[:40].strip("-") or "desk-task"


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


def start(
    instruction: str, *, cwd: str, name: str, env: Mapping[str, str] | None = None
) -> Started:
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

    # Secrets the work needs, handed to the child the way secrets are handed to processes: in its
    # environment, for the life of that process, and never written anywhere by this program
    # (agent_desk/secrets.py). What is passed is decided by the caller and named in the console.
    environment = {**os.environ, **(env or {})}

    try:
        done = subprocess.run(  # noqa: S603 — a list, no shell, and the binary is from settings
            command,
            cwd=directory,
            env=environment,
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


def kick(session_id: str, instruction: str, *, cwd: str, agent_id: str = "") -> Started:
    """Continue one idle background session with one more turn (docs/adr/0009).

    Two calls, because the CLI needs both: `--resume` "works once it is stopped", and a `--bg`
    session that has finished a turn is still running — it idles at its prompt with its process
    alive. So the session is stopped first, which keeps the conversation, and then continued under
    the same id.

    A stop that fails is not fatal and is not reported: the session may have exited between the
    registry being read and this running, and the resume is what actually has to work.

    Never raises, for the same reason `start` does not.
    """
    if not instruction.strip():
        return Started(False, detail="there is nothing written to send")
    if not session_id:
        return Started(False, detail="that session has no id to resume")
    directory = Path(cwd)
    if not directory.is_dir():
        return Started(False, detail=f"{cwd} is not a directory on this machine any more")
    if shutil.which(settings.claude_bin) is None and not Path(settings.claude_bin).exists():
        return Started(False, detail=f"{settings.claude_bin} is not installed here")

    if agent_id:
        stop(agent_id)

    command = resume_argv(session_id, instruction)
    forbidden = [flag for flag in command if flag in NEVER]
    if forbidden:  # pragma: no cover — the argv builder cannot produce one; the check is the rule
        return Started(False, detail=f"refusing to continue a session with {forbidden[0]}")

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
        return Started(False, detail=f"could not continue it: {type(exc).__name__}")

    said = (done.stderr or done.stdout).strip()
    short = _read_id(done.stdout) or session_id.split("-")[0]
    if done.returncode != 0:
        lines = said.splitlines()
        return Started(False, detail=lines[-1][:300] if lines else f"exit {done.returncode}")
    return Started(True, agent_id=short)


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
