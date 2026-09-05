"""Secrets, kept on the machine they were typed on and shown to nobody.

The console asks for tokens — a tracker, a repository host — and the person using it wants to type
them there rather than export a variable in a shell. That is reasonable, and the earlier answer
(refuse the field) was the wrong shape of no. What was actually wrong was *where* they went: into
the SQLite file the shared application serves a redacted view out of, and back onto a page.

So they live here instead, and the rules are the ones that make the field safe to have:

- **One file, this machine, mode 0600.** Not the store: nothing that answers a network request
  ever opens this. A console deployed somewhere else keeps its own, and a secret typed here does
  not travel with the database.
- **Write and use, never read back to a screen.** There is no route that returns a value and no
  template that could render one. The console can say *set* or *not set*, which is what somebody
  needs to know, and that answer comes from `has()`.
- **Named by the same key the link already carries**, so nothing new has to be remembered: the
  variable name on a project's link is the name of the secret.
- **The environment still wins.** A variable exported in the shell that started the console is
  used in preference to anything stored here, because that is the arrangement an operator with a
  secret manager will have, and this file must not quietly shadow it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_desk.config import settings

# Mode 0600 on the file and 0700 on its directory: on a shared machine, "only this user" is the
# whole of the protection this offers, and it is stated rather than assumed.
_FILE_MODE = 0o600
_DIR_MODE = 0o700


def path() -> Path:
    return settings.data_dir / "secrets.json"


def _read() -> dict[str, str]:
    try:
        content = json.loads(path().read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in content.items()} if isinstance(content, dict) else {}


def _write(values: dict[str, str]) -> None:
    """Replace the file, and never let it exist readable — not even for a moment.

    The obvious version writes the file and then chmods it, which leaves every secret in it
    world-readable for as long as that takes. On a shared machine that window is the whole
    vulnerability, so the mode is given to `open` rather than applied after it: the descriptor
    never exists at any other permission (docs/07-security.md).
    """
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, _DIR_MODE)

    # Written to a neighbour and moved into place: a crash halfway through a rewrite would
    # otherwise leave every secret in the file truncated. `O_EXCL` so that a stale one left by a
    # crash is not written into blindly.
    beside = target.with_suffix(".writing")
    beside.unlink(missing_ok=True)
    descriptor = os.open(beside, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(json.dumps(values, indent=2, sort_keys=True))
    beside.replace(target)


def keep(name: str, value: str) -> None:
    """Store one secret under a name. An empty value removes it."""
    values = _read()
    if value:
        values[name] = value
    else:
        values.pop(name, None)
    _write(values)


def forget(name: str) -> None:
    keep(name, "")


def has(name: str) -> bool:
    """Whether there is a value for this name — never what it is.

    The environment counts: a variable exported in the shell is what would actually be used.
    """
    return bool(name) and (bool(os.environ.get(name)) or name in _read())


def get(name: str) -> str:
    """The value, for the one caller that makes a request with it.

    Nothing renders this. The environment wins, so an operator with a secret manager is not
    shadowed by something typed into a browser months ago.
    """
    return os.environ.get(name) or _read().get(name, "")
