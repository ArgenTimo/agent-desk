"""Adding a project by pointing at it, rather than by having run something in it.

A project appears on this board the first time somebody runs `claude` in it, and that is the whole
of the setup — it is the answer in the README and it is the right default. It is not the whole
story, though, and one idea in the pool says so: *"при добавлении проекта можно просто указать
ссылку на репозиторий либо указать папку на устройстве либо другие удобные способы"*.

Both of those are things somebody has in their hand at the moment they think of the project, and
neither requires them to go and start a session first. So:

- **a folder** — the ordinary case, and the only one that needs nothing but a look at the disk;
- **a repository URL** — an ssh or https remote, which names a project that may not be on this
  machine yet, and says where to get it;
- and the console keeps saying that running `claude` anywhere is still the way that needs no form
  at all.

What this module does *not* do is clone anything. This program is a reader of repositories
(CLAUDE.md, rule two): it will happily record where one lives, and it will not fetch it, create
it, or write a line into it. A URL with no checkout on this machine is recorded as a project with
a link and no instance, which is exactly what it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from agent_desk.observe.shape import repository_of

# The two shapes a remote comes in. `git@host:owner/name.git` and `https://host/owner/name`, which
# are the two things a "copy" button on a forge puts on somebody's clipboard.
_SSH = re.compile(
    r"\A(?:ssh://)?git@([A-Za-z0-9.\-]+)[:/]([A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+?)(?:\.git)?/?\Z"
)
_HTTPS = re.compile(
    r"\Ahttps?://([A-Za-z0-9.\-]+)/([A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+?)(?:\.git)?/?\Z"
)


@dataclass(frozen=True)
class Pointed:
    """What somebody pointed at, read back as this program understands it."""

    ok: bool
    # The key the board files it under, in the same shape `observe/shape.py` produces.
    repo_key: str = ""
    name: str = ""
    # Where it is on this machine, when it is.
    path: str = ""
    # Where to get it, when they gave a remote.
    url: str = ""
    detail: str = ""


def _from_remote(said: str) -> tuple[str, str] | None:
    """`(host, owner/name)` for a remote this understands, or `None`."""
    for pattern in (_SSH, _HTTPS):
        match = pattern.match(said)
        if match is not None:
            return match.group(1), match.group(2)
    return None


def read(said: str) -> Pointed:
    """What was pointed at. Never raises and never touches the network.

    A folder is checked against the disk because a path that is not there is a typo, and saying so
    now is cheaper than a project card that never fills in. A remote is not checked against
    anything: this program does not fetch, and a URL that is wrong is a link that does not open,
    which is visible without asking anybody.
    """
    said = said.strip()
    if not said:
        return Pointed(False, detail="nothing was typed")

    remote = _from_remote(said)
    if remote is not None:
        host, full = remote
        name = full.split("/")[-1]
        # The same key shape `observe/shape.py` gives a checkout with this origin, so a project
        # added this way and the same project discovered later are one project rather than two.
        return Pointed(
            True,
            repo_key=f"origin:{full}",
            name=name,
            url=said if said.startswith("http") else f"https://{host}/{full}",
        )

    if said.startswith(("http://", "https://", "git@", "ssh://")):
        return Pointed(False, detail="that looks like a URL, but not one naming a repository")

    where = Path(said).expanduser()
    if not where.is_absolute():
        return Pointed(False, detail="a folder has to be a full path, starting at /")
    if not where.is_dir():
        return Pointed(False, detail=f"{where} is not a folder on this machine")
    # The board's own answer to "which repository is this", not a second one. A folder that turns
    # out to be a checkout gets the key its origin gives it — so a project added by pointing at it
    # and the same project discovered when a session starts there are one project, not two.
    found = repository_of(str(where))
    return Pointed(True, repo_key=found.key, name=found.name, path=str(where))
