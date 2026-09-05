"""How a dispatched agent ended, in the CLI's own words.

`claude --bg` keeps a small state file per background job — `~/.claude/jobs/<short>/state.json` —
and it is the only place on disk that says whether a job *finished* or *died*. The registry
(`registry.py`) holds live sessions and nothing else, so a job that is not in it has merely gone;
this module is what distinguishes gone-because-done from gone-because-it-never-started.

That distinction is the fifth rule in CLAUDE.md. Six dispatched agents exited in under a second on
a worktree name the CLI would not accept, and the console reported all six as finished work,
because "the session is no longer in the registry" was the only fact it had. It is not the only
fact available — it was the only one being read.

Read-only, and the same posture as every other reader here: the glob is the one file this module
names, the shape is validated at the boundary (docs/adr/0004), and a file that has been cleaned up
is an absence rather than an error.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from agent_desk.config import settings
from agent_desk.observe.model import JobEnd


def state_path(short_id: str) -> Path:
    """Where the CLI keeps one background job's state.

    A single path segment, checked: `short_id` reaches this from a database row that a dispatch
    wrote, and a reader that would follow `../..` out of `~/.claude/jobs/` on a bad one is a reader
    somebody has to think about later.
    """
    if not short_id or "/" in short_id or short_id in (".", ".."):
        return settings.jobs_root / "-"
    return settings.jobs_root / short_id / "state.json"


def read_job(short_id: str) -> JobEnd | None:
    """What became of one dispatched agent, or `None` when the CLI has nothing to say.

    `None` is not a failure and must not be read as one: the job directory is removed by
    `claude rm`, and an old job that has been tidied away is silent rather than broken. The caller
    that cannot tell should keep saying it cannot tell.
    """
    try:
        raw = state_path(short_id).read_text()
    except OSError:
        return None
    try:
        return JobEnd.model_validate(json.loads(raw))
    except (ValidationError, json.JSONDecodeError):
        return None
