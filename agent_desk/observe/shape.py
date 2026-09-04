"""What the sessions on this machine add up to: agents, instances and repositories.

The board began as a flat list of sessions because that is what the registry is. It is not what a
person has in their head. A person has projects, each of which is one or more checkouts, each of
which may have a console or two open in it, and each of those may have farmed work out to
subagents. Four levels, and every one of them is derivable from what is already on disk — which
matters, because a level that had to be *declared* would go stale the first time somebody forgot
to (docs/adr/0004 is the same argument about a different file).

- **an agent** is a subagent a session started: a `tool_use` named `Agent`, carrying the type and
  the one-line description the session gave it. Its `tool_result` is how we know it finished.
- **a session** is one registry entry — one console.
- **an instance** is one working directory. Two consoles open in the same checkout are two
  sessions of one instance.
- **a repository** is what groups instances by default: a worktree's `.git` is a file pointing at
  the checkout it belongs to, and a clone's `.git/config` names an origin. Two directories that
  resolve to the same origin are the same repository even though they are different folders.

Nothing here runs `git`. It reads two small files, which is the same promise the rest of this
package makes: the observed repository cannot tell that it happened.
"""

from __future__ import annotations

import configparser
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class Repository(BaseModel):
    """How a checkout identifies the project it belongs to."""

    model_config = ConfigDict(frozen=True)

    # Stable across worktrees and clones when there is an origin; the resolved git directory when
    # there is not; the directory itself when there is no git at all.
    key: str
    # What a human would call it: the last path segment of the origin, or of the checkout.
    name: str
    origin: str | None = None


def _git_dir(cwd: Path) -> Path | None:
    """The git directory a checkout belongs to, following a worktree's pointer.

    A worktree's `.git` is a file reading `gitdir: /path/to/main/.git/worktrees/<name>`, and the
    repository it belongs to is two levels above that — which is why a worktree and its main
    checkout are one project here rather than two.
    """
    marker = cwd / ".git"
    try:
        if marker.is_dir():
            return marker
        if marker.is_file():
            pointer = marker.read_text().strip()
            if not pointer.startswith("gitdir:"):
                return None
            path = Path(pointer.split(":", 1)[1].strip())
            if path.parent.name == "worktrees":
                return path.parent.parent
            return path
    except OSError:
        return None
    return None


def _origin(git_dir: Path) -> str | None:
    """The origin URL from a git config, read as a file rather than asked of `git`."""
    parser = configparser.ConfigParser()
    try:
        parser.read_string((git_dir / "config").read_text())
    except (OSError, configparser.Error):
        return None
    for section in parser.sections():
        if section.replace('"', "").strip() == "remote origin":
            return parser[section].get("url")
    return None


def _readable(url: str) -> str:
    """`git@github.com:owner/repo.git` and `https://…/owner/repo` both become `owner/repo`."""
    trimmed = url.removesuffix(".git").rstrip("/")
    if ":" in trimmed and "//" not in trimmed:
        trimmed = trimmed.split(":", 1)[1]
    parts = [part for part in trimmed.split("/") if part]
    return "/".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else url)


def repository_of(cwd: str) -> Repository:
    """Which repository a working directory belongs to.

    Never raises and never asks the network: a directory that is not a checkout is its own
    repository, which is exactly right for a folder somebody is working in without git.
    """
    path = Path(cwd)
    git_dir = _git_dir(path)
    if git_dir is None:
        return Repository(key=f"dir:{cwd}", name=path.name or cwd)

    origin = _origin(git_dir)
    if origin:
        return Repository(key=f"origin:{_readable(origin)}", name=_readable(origin), origin=origin)
    # A repository with no remote is still one repository — every worktree of it resolves here.
    return Repository(key=f"git:{git_dir}", name=git_dir.parent.name or path.name)
