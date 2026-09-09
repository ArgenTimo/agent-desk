"""Opening a session on the screen of the machine this console is running on.

*«Кнопка "перейти" должна открывать сессию на экране устройства… Страница не может открыть терминал
сама, и кнопка, которая делает вид что может, была бы хуже — но настоящее "перейти" возможно:
маленький локальный хелпер, который консоль дёргает, или зарегистрированная схема ссылок.»*

The page still cannot open a terminal, and that was never the question: the console is a process on
the same machine, started by the same person, and it can. So the button posts, and this starts
`claude attach <id>` in whatever terminal is installed.

## Why this is not a write into somebody's session

Nothing is typed into it. What happens is a window opening in front of the person who pressed the
button, with their own session in it — after which they type, or do not. docs/adr/0002 is about this
program putting text into a context; this puts a person in front of one.

## A closed list of terminals, and no shell

Each entry is a command and the flag it takes before the thing to run, and the whole argv is a list
— so a session id never reaches a shell. The first one on PATH wins, in the order below, which puts
the distribution's own choice (`x-terminal-emulator`) ahead of any particular desktop's.

A machine with none of them is told so, and the button falls back to what it did before: copying the
exact line to paste. That is the honest half, and it stays.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from agent_desk.config import settings

# What runs the command, and the flag each one takes before it. `x-terminal-emulator` first: it is
# the distribution's own answer to "the terminal", and going round it would open a window somebody
# did not choose.
TERMINALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("x-terminal-emulator", ("-e",)),
    ("gnome-terminal", ("--",)),
    ("konsole", ("-e",)),
    ("xfce4-terminal", ("-x",)),
    ("kitty", ()),
    ("alacritty", ("-e",)),
    ("foot", ()),
    ("xterm", ("-e",)),
)

# How long to wait for the terminal to come up. It returns immediately or it is not going to: this
# is a bound on a mistake rather than a timeout anybody should reach.
SECONDS = 10.0


@dataclass(frozen=True)
class Opened:
    """What happened when the button was pressed."""

    ok: bool
    detail: str = ""


def a_terminal() -> tuple[str, tuple[str, ...]] | None:
    """The first terminal on this machine, or `None`."""
    for name, flag in TERMINALS:
        if shutil.which(name):
            return name, flag
    return None


def argv(session_id: str) -> list[str] | None:
    """The whole command, as a list, so that a test can read it and a shell never sees it."""
    found = a_terminal()
    if found is None or not session_id.strip():
        return None
    name, flag = found
    return [name, *flag, settings.claude_bin, "attach", session_id.strip()]


def open_it(session_id: str) -> Opened:
    """Open the session in a terminal. Blocking: the caller runs it in a thread.

    Never raises. Every ending is an `Opened`, because this is reached from a route that has to
    render something either way — and the something is the same button, saying what happened.
    """
    command = argv(session_id)
    if command is None:
        return Opened(
            False,
            "there is no terminal on this machine that this console knows how to open — "
            "the command is copied instead",
        )
    try:
        subprocess.Popen(  # noqa: S603 — a list, no shell, and every part of it is from settings
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Opened(False, f"it would not open: {type(exc).__name__}")
    return Opened(True, f"opened in {command[0]}")
