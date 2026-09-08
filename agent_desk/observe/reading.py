"""Opening one file, because somebody said this one may be opened.

`agent_desk/observe/folder.py` lists a directory and never opens anything in it, and that rule is
absolute — a test walks its syntax tree to make sure of it. This is the other half of the same
argument rather than an exception to it: *"«Собери из них» означает, что файлы будут прочитаны —
значит, это отдельное разрешение, которое человек даёт явно, а не побочный эффект просьбы."*

It is a module of its own so that both rules can be stated without qualification. "The folder
reader never opens a file" stays true and stays checkable; "this opens a file, and only one
somebody clicked" is the whole of what is here.

Three limits, and none of them is a preference:

- **A credential is refused whatever anybody clicked.** The third of the five rules in CLAUDE.md is
  not a default to be overridden, so it is checked here as well as at the door that writes the
  permission down. A rule that holds only where a caller remembered to ask is not a rule.
- **Text only.** A picture in a prompt is bytes nobody can read and a bill nobody agreed to.
- **A cap.** A file is dropped on a bench so a question can be asked against it, and a question
  asked against four hundred kilobytes is a question nobody can afford twice. What was left out is
  counted out loud, because quietly answering about the first half of a file is worse than saying
  so.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# How much of a file goes into a prompt. A file is dropped on a bench so that a question can be
# asked against it, and a question asked against four hundred kilobytes is a question nobody can
# afford twice. Past this the card says how much was left out, which is a different thing from
# quietly answering about the first half.
MOST_CHARS = 20_000


# Paths no click can unlock. The third of the five rules in CLAUDE.md is not a default somebody may
# override, so this is checked in the reader rather than at the door: a permission row for one of
# these is never written, and if one existed it would still not be read.
#
# `.env` by name and by suffix, because `.env.local` and `prod.env` are the same file with the same
# contents. Anything under `~/.claude` because that is where the account token and the peer keys
# live, and a text file beside them is not worth the risk of getting the pattern slightly wrong.
def is_a_credential(where: Path) -> bool:
    """Whether this path is one nothing here may open, whatever anybody has clicked."""
    name = where.name.lower()
    if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
        return True
    if name.endswith((".key", ".pem", ".p12", ".pfx")):
        return True
    claude = Path.home() / ".claude"
    return where == claude or claude in where.parents


@dataclass(frozen=True)
class Said:
    """What one file says, or why it does not say anything here."""

    ok: bool
    path: str = ""
    text: str = ""
    detail: str = ""
    # How much was not read. Zero when the whole file is here, which is the ordinary case.
    left_out: int = 0


def read_file(said: str) -> Said:
    """The text of one file. Never raises, and never opens what it must not.

    Called only for a path somebody has clicked to allow — that check belongs to the caller, which
    is where the click is known — and this refuses on top of it anyway for the paths no click can
    unlock. Two checks for one rule, deliberately: the caller's is the permission and this one is
    the rule, and a rule that only holds where a caller remembered to ask is not a rule.
    """
    where = Path(said.strip()).expanduser()
    if not said.strip() or not where.is_absolute():
        return Said(False, detail="a file has to be a full path, starting at /")
    if is_a_credential(where):
        return Said(False, path=str(where), detail="this program does not open credentials")
    if not where.is_file():
        return Said(False, path=str(where), detail=f"{where} is not a file on this machine")
    try:
        raw = where.read_bytes()
    except OSError as exc:
        return Said(False, path=str(where), detail=f"could not read it: {type(exc).__name__}")
    if b"\0" in raw[:4096]:
        # Something that is not text. A picture in a prompt is bytes nobody can read and a bill
        # nobody agreed to.
        return Said(False, path=str(where), detail="that one is not a text file")
    text = raw.decode("utf-8", errors="replace")
    return Said(
        True,
        path=str(where),
        text=text[:MOST_CHARS],
        left_out=max(0, len(text) - MOST_CHARS),
    )
