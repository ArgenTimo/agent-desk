"""The registry: one file per live session, and the check that it is still true.

A file here is a *claim* about a process, and the claim is checkable. Believing it is how a board
shows a session that died an hour ago as `busy` — which is the single failure that makes a status
board worthless, because the whole product is that you can trust it at a glance
(docs/03-session-observation.md).

Read-only, always. The glob is `*.json` and never `*`: the `.key` files beside these entries
authenticate a session's messaging socket, and this process has no business holding one
(docs/07-security.md).
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

from pydantic import ValidationError

from agent_desk.config import settings
from agent_desk.observe.model import RECORDED_CLI_VERSION, RegistryRead, Session

PROC = Path("/proc")

# `starttime` is field 22 of /proc/<pid>/stat. Fields 1 (pid) and 2 (comm) are consumed before the
# split, because comm is the process name in parentheses and may contain both spaces and
# parentheses — which is what makes the obvious `stat.split()[21]` wrong for exactly the processes
# whose name someone chose badly.
_STARTTIME_INDEX = 22 - 3


def _starttime(pid: int, proc_root: Path) -> str | None:
    try:
        stat = (proc_root / str(pid) / "stat").read_text()
    except OSError:
        return None
    end_of_comm = stat.rfind(")")
    if end_of_comm < 0:
        return None
    fields = stat[end_of_comm + 1 :].split()
    if len(fields) <= _STARTTIME_INDEX:
        return None
    return fields[_STARTTIME_INDEX]


def is_alive(pid: int, proc_start: str, *, proc_root: Path = PROC) -> bool:
    """Two checks, not one: the process exists, and it is the same process.

    The second is what survives pid reuse, and it is why `procStart` is in the registry file at
    all (docs/03-session-observation.md).
    """
    if not (proc_root / str(pid)).exists():
        return False
    return _starttime(pid, proc_root) == proc_start


def _is_newer(observed: str, recorded: str) -> bool:
    """Is `observed` a version the fixtures were recorded before?

    The banner of docs/adr/0004 is direction-sensitive, and it has to be to stay readable. A
    session *newer* than the recording is the case that ADR is about: a field may have moved and
    nothing announced it, so the shape is unverified and the board says so. A session *older* than
    the recording raises nothing, for two reasons — an older shape that no longer fits the model
    already produces its own, far more specific notice naming the field, and on a machine where a
    session runs for days there is always one, so a banner lit by age is a banner nobody reads.

    A version that is not dotted integers is reported: unknown is not evidence of sameness.
    """
    try:
        return tuple(int(part) for part in observed.split(".")) > tuple(
            int(part) for part in recorded.split(".")
        )
    except ValueError:
        return True


def _is_headless(entry: object) -> bool:
    """Is this a program's own run rather than a human's session?

    A headless `claude -p` registers itself like any other session, with `entrypoint` naming the
    SDK that started it — and it publishes no `status`, because nothing is watching it work. Two
    consequences, both found by running this tool against its own machine rather than by reading
    the file format:

    The board must not show them. They are not sessions a human triages; they appear and vanish
    with every question typed into this console, and one of them is *this program answering that
    question* (docs/06-console.md — the board is what needs a human).

    And they must not raise the banner. An entry with no `status` is not a shape that moved, it is
    a different shape, and a warning that fires on normal operation is a warning nobody reads
    (docs/adr/0004).
    """
    return isinstance(entry, dict) and str(entry.get("entrypoint", "")).startswith("sdk-")


def _why(exc: Exception) -> str:
    """A reason a human can act on, carrying no content out of the file.

    A registry entry names a working directory and a session id; an error message that quotes the
    value it choked on puts that into a log line and a rendered banner. The field name is what
    identifies the drift, and the field name is enough (docs/07-security.md).
    """
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
    if isinstance(exc, json.JSONDecodeError):
        return f"not JSON ({exc.msg} at line {exc.lineno})"
    return type(exc).__name__


def read_registry(*, pattern: str | None = None, proc_root: Path = PROC) -> RegistryRead:
    """Every live session, plus what could not be read.

    An entry failing the liveness check is not reported: a session that ended is the normal case,
    not a problem. An entry that no longer *parses* is reported, because that is the format having
    moved under the program, and a quiet `None` there is the failure docs/adr/0004 exists to
    prevent.
    """
    sessions: list[Session] = []
    notices: list[str] = []

    for path in sorted(Path(p) for p in glob.glob(pattern or settings.registry_glob)):
        try:
            entry = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            notices.append(f"{path.name}: {_why(exc)}")
            continue
        if _is_headless(entry):
            continue
        try:
            session = Session.model_validate(entry)
        except ValidationError as exc:
            notices.append(f"{path.name}: {_why(exc)}")
            continue
        if is_alive(session.pid, session.proc_start, proc_root=proc_root):
            sessions.append(session)

    ahead = sorted({s.version for s in sessions if _is_newer(s.version, RECORDED_CLI_VERSION)})
    if ahead:
        notices.append(
            f"CLI {', '.join(ahead)} is newer than the {RECORDED_CLI_VERSION} the fixtures were "
            f"recorded from — a shape may have moved without announcing it. If a row looks wrong, "
            f"re-record (docs/adr/0004)."
        )
    return RegistryRead(sessions=sessions, notices=notices)
