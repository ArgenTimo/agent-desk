"""Sessions that belong to another executor, and are not this board's to show (task 21).

ai-worker runs its own agents — as its own OS user, in its own workspaces — and reports them
through its own API (ADR 0014, proposed). If one of them ever surfaces in this machine's registry
or job list, it is not a session somebody here is working in, and its transcript holds a client's
code and a ticket's text that this console has no business rendering. So everything under
`settings.aiworker_workspace_roots` is left out *before* anything about it is read.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_desk.config import settings


def _roots() -> list[Path]:
    return [
        Path(one.strip()) for one in settings.aiworker_workspace_roots.split(",") if one.strip()
    ]


def elsewhere(cwd: str) -> bool:
    """Is this working directory under another executor's roots?"""
    if not cwd:
        return False
    here = Path(cwd)
    return any(here == root or here.is_relative_to(root) for root in _roots())


def elsewhere_slug(directory: str) -> bool:
    """The same question about a transcript directory, whose name is the cwd with every
    non-alphanumeric character turned into '-'. That is lossy, so this can hide a directory it
    should not (`/home/aiw-x`) and never shows one it should hide — the safe direction."""
    return any(directory.startswith(re.sub(r"[^A-Za-z0-9]", "-", str(root))) for root in _roots())
