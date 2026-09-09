"""Starting a project this console will then watch like any other.

"…заканчивая полноценным проектом (с его отслеживанием и прочим). Поднимается объективное
количество инстансов, сессий, агентов." A repository somebody points at, brought onto this machine,
with the first piece of work queued in it — and from there nothing is special about it: a session
runs in a directory, the board shows it, the blockers watch it, the budget bounds it.

## Where it goes, and why that is not a preference

`config.py` says `data_dir` is "the only tree this program writes to", and CLAUDE.md's second rule
says this program never writes into an observed repository. A clone is a write, so it goes under
`data_dir`. That keeps both sentences true at once: the checkout is *not* one of the repositories
this console reads over somebody's shoulder, it is one this console made, in the one place it owns.

## The token is not in the command

`/proc/<pid>/cmdline` is world-readable, which is why the prompt goes to the answer engine on stdin
and why a URL with a credential in it would be the same mistake in a different shape. Git is given
a credential helper — a shape, in argv — that reads the secret out of the environment, which is
readable only by the same user this process already runs as.

## What it does not do

It does not start an agent. Queueing work and starting it are two acts here and the second is a
click (docs/adr/0002, docs/adr/0007), and a route that cloned a repository *and* set something
running on it would be the automatic queue those documents are built to avoid.

`checkout` is the same clone asked for at the other end, by somebody pressing "make an instance"
on a project that is only an address. That press is already the click adr/0006 requires, and the
agent it starts is the thing it was pressed for — so the clone is part of one human act rather
than a second one nobody asked for.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Long enough for a big first clone on a slow line, short enough that a wrong address does not hold
# a request open until somebody reloads the page.
CLONE_TIMEOUT_SECONDS = 180.0

# The helper git is given. It is a shape and not a secret: the token is `$GIT_ACCESS_TOKEN` in the
# environment of the child, which is where a secret belongs when a process needs one.
_HELPER = "!f() { echo username=x-access-token; echo password=$GIT_ACCESS_TOKEN; }; f"

_OWNER_AND_NAME = re.compile(r"/([A-Za-z0-9._\-]+)/([A-Za-z0-9._\-]+?)(?:\.git)?/?\Z")


@dataclass(frozen=True)
class Made:
    """What one attempt produced, or why it produced nothing."""

    ok: bool
    cwd: str = ""
    repo_key: str = ""
    name: str = ""
    detail: str = ""


def key_and_name(url: str) -> tuple[str, str]:
    """The project key and the readable name for a repository address.

    The key is `origin:<owner>/<name>`, which is the shape every other project on this board
    already has, so a project this console started sorts and groups with the rest instead of
    forming a second kind of thing.
    """
    found = _OWNER_AND_NAME.search(url.strip())
    if found is None:
        return "", ""
    owner, name = found.group(1), found.group(2)
    return f"origin:{owner}/{name}", name


def where(data_dir: Path, url: str) -> Path:
    """The directory this repository would be cloned into. Inside the one tree this program owns.

    Named after the repository rather than by a counter, because somebody is going to open a
    terminal in it eventually and `~/.local/share/agent-desk/projects/proto` is a path they can
    read.
    """
    _, name = key_and_name(url)
    return data_dir / "projects" / (name or "project")


def clone(url: str, into: Path, *, token: str = "") -> Made:
    """Bring the repository onto this machine. Blocking: the caller runs it in a thread.

    Never raises. Every ending is a `Made`, because this is reached from a route that has to render
    something either way — the same rule `dispatch.start` is written under.
    """
    repo_key, name = key_and_name(url)
    if not repo_key:
        return Made(False, detail=f"{url} does not look like a repository address")
    if not url.startswith("https://") and not url.startswith("file:///") and "://" in url:
        # https, or a local path for a test. Anything else — ssh, git:// — needs a key nobody typed
        # and would hang on a prompt this console cannot answer.
        return Made(False, detail="only https addresses can be cloned from here")
    if into.exists():
        return Made(False, cwd=str(into), detail=f"{into} is already here — it was not touched")

    into.parent.mkdir(parents=True, exist_ok=True)
    # The token in the environment and never in argv. `-c` carries the helper's *shape*, which is
    # what `/proc/<pid>/cmdline` will show.
    environment = {**os.environ}
    command = ["git"]
    if token:
        environment["GIT_ACCESS_TOKEN"] = token
        command += ["-c", f"credential.helper={_HELPER}"]
    command += ["clone", "--", url, str(into)]
    try:
        done = subprocess.run(  # noqa: S603 - a fixed argv, and the URL is checked above
            command,
            env={**environment, "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Made(False, detail=f"could not run git: {type(exc).__name__}")
    if done.returncode != 0:
        # The last line of what git said, and never the command: the command names the helper, and
        # a reader who saw it might reasonably paste it somewhere with the token filled in.
        said = (done.stderr or done.stdout or "").strip().splitlines()
        return Made(False, detail=said[-1][:200] if said else f"git exited {done.returncode}")
    return Made(True, cwd=str(into), repo_key=repo_key, name=name)


def checkout(data_dir: Path, url: str, *, token: str = "") -> Made:
    """Where this repository is on this machine, cloning it if it is not here yet.

    The difference from `clone` is what "already here" means. `clone` refuses a directory that
    exists, which is right for the act of starting a project — doing it twice by accident should
    not silently reuse whatever is in the way. This is asked by somebody making a *second* instance
    of a project they already made a first one of, and there the answer to "it is already here" is
    the path, not an error.

    A directory that is there and is not a checkout is still a refusal. It is the one case where
    the two readings differ and guessing would be writing an agent into somebody's stray folder.
    """
    into = where(data_dir, url)
    repo_key, name = key_and_name(url)
    if not into.exists():
        return clone(url, into, token=token)
    if not (into / ".git").exists():
        return Made(False, cwd=str(into), detail=f"{into} is here but is not a checkout")
    return Made(True, cwd=str(into), repo_key=repo_key, name=name, detail="already on this machine")


def first_task(said: str, url: str, links: tuple[str, ...] = ()) -> str:
    """What the first agent in the new checkout is told.

    The person's own words first, because they are the brief and everything else here is context
    for it. What is deliberately absent is any instruction to push, publish or open anything: this
    is a checkout on somebody's machine and what happens to it next is theirs to decide.
    """
    lines = [said.strip() or "Make a start on this.", "", f"The repository is {url}."]
    if links:
        lines += ["", "References given with the request:"]
        lines += [f"- {one}" for one in links]
    lines += [
        "",
        "This checkout was made by the console you are running in, in its own data directory. "
        "Work in it as you would in any other. Nothing here pushes, publishes or opens anything "
        "on your behalf.",
    ]
    return "\n".join(lines)
