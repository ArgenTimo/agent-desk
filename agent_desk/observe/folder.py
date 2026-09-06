"""A folder on somebody's machine, read as a list of what is in it.

"По ПКМ на верстаке можно добавить целую папку с устройства — точнее ссылку на неё. Каждый файл и
подпапка внутри становится мини-карточкой, и рядом с названием ЛЛМ пишет, что этот файл или папка
делает."

The reading is the easy half and the *not* reading is the point. This program is a reader of other
people's directories (CLAUDE.md, rule two) and it stays one here:

- **A link, not a copy.** Nothing is uploaded, nothing is stored but the path. What travels with a
  message is what the folder contains, not what the files say.
- **One level.** A folder is a card; opening a subfolder is another card. Walking the whole tree of
  somebody's home directory because they dropped it on the workbench is not a feature.
- **Names, sizes and kinds only.** File *contents* are not read. A directory somebody points at may
  hold anything — keys, exports, somebody else's data — and the difference between listing a
  filename and opening it is the whole of why this is safe to offer.
- **Nothing hidden is listed**, because a dotfile is usually configuration rather than work, and
  the ones that are not are the ones most likely to hold a credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# How many entries one folder card lists. A directory with four hundred files in it is not a card,
# and the ones after this are reached by opening the folder itself.
MOST_ENTRIES = 40

# What a file is, in the words the card uses. Deliberately coarse: this is a hint beside a name,
# not a type system.
KINDS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".html": "a page",
    ".css": "styles",
    ".md": "notes",
    ".txt": "notes",
    ".json": "data",
    ".yaml": "settings",
    ".yml": "settings",
    ".toml": "settings",
    ".sql": "sql",
    ".sh": "a script",
    ".png": "an image",
    ".jpg": "an image",
    ".svg": "an image",
    ".pdf": "a document",
    ".csv": "a table",
}


@dataclass(frozen=True)
class Entry:
    """One thing in a folder."""

    name: str
    is_folder: bool
    kind: str
    size: int


@dataclass(frozen=True)
class Folder:
    """What is in one folder, or why it could not be read."""

    ok: bool
    path: str = ""
    entries: tuple[Entry, ...] = ()
    detail: str = ""


def _kind(where: Path) -> str:
    if where.is_dir():
        return "folder"
    return KINDS.get(where.suffix.lower(), where.suffix.lstrip(".") or "a file")


def read(said: str) -> Folder:
    """What is in the folder somebody pointed at. Never raises and never opens a file."""
    said = said.strip()
    if not said:
        return Folder(False, detail="nothing was typed")
    where = Path(said).expanduser()
    if not where.is_absolute():
        return Folder(False, detail="a folder has to be a full path, starting at /")
    if not where.is_dir():
        return Folder(False, detail=f"{where} is not a folder on this machine")

    found: list[Entry] = []
    try:
        for child in sorted(where.iterdir(), key=lambda one: (not one.is_dir(), one.name.lower())):
            if child.name.startswith("."):
                # A dotfile is usually configuration rather than work, and the ones that are not
                # are the ones most likely to hold a credential.
                continue
            try:
                size = child.stat().st_size if child.is_file() else 0
            except OSError:
                size = 0
            found.append(
                Entry(name=child.name, is_folder=child.is_dir(), kind=_kind(child), size=size)
            )
            if len(found) >= MOST_ENTRIES:
                break
    except OSError as exc:
        return Folder(False, path=str(where), detail=f"could not read it: {type(exc).__name__}")

    return Folder(True, path=str(where), entries=tuple(found))


def about(folder: Folder) -> str:
    """What a folder is, for a model to write a sentence from — names and kinds, never contents."""
    return "\n".join(
        [f"folder: {folder.path}"]
        + [
            f"- {one.name}{'/' if one.is_folder else ''} ({one.kind})"
            for one in folder.entries[:MOST_ENTRIES]
        ]
    )
