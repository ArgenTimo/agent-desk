"""The machine this suite runs on is not an input to it.

`Settings` resolves `claude_home`, `data_dir` and `claude_bin` from the environment (config.py),
and half the package binds `settings` at module import. So the redirect has to happen here, at
the top of the one file pytest loads before any test module — an empty `~/.claude`, an empty
`data_dir` and a CLI that does not exist, for every test, whether or not it remembered to ask.

Three doors, each of which has already been walked through:

- `claude_bin`. The CLI is resolved from PATH, and on the machine this suite usually runs on it is
  there. A test that reached `dispatch.start` without faking it started a real `claude --bg` agent
  — in a worktree of whichever checkout ran the gate — and a test that reached the answer engine
  spent a real `claude -p` call. The Stop hook runs the gate at every turn end, which made that one
  agent, named after the test's input, every few minutes: fifty-four of them told only "бери в
  работу" in one day (docs/adr/0006 — an agent is started by a click, never by a background loop).
  It is pointed at a name inside the empty tree that nothing will ever create, so every such path
  becomes the one it already handles: the CLI is not installed here.
- `data_dir`. `web/routes.py` opens `settings.db_path` at import, which without this is the
  console's own database, live, while its owner is using it — migrated by whatever branch ran the
  gate, its running blocks marked failed by `_recover_interrupted`, its `secrets.json` rewritten.
- `claude_home`. A test that renders the board without redirecting reads the real registry and the
  tail of every live session, so its assertions are about whatever an agent working beside the
  suite happened to be saying.

Set rather than defaulted: a value already in somebody's environment is exactly the value this
must not use. A test that wants a CLI or a store builds its own.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_ELSEWHERE = Path(tempfile.mkdtemp(prefix="agent-desk-suite-"))
(_ELSEWHERE / "claude" / "sessions").mkdir(parents=True)
(_ELSEWHERE / "claude" / "projects").mkdir(parents=True)
os.environ["AGENT_DESK_CLAUDE_HOME"] = str(_ELSEWHERE / "claude")
os.environ["AGENT_DESK_DATA_DIR"] = str(_ELSEWHERE / "data")
os.environ["AGENT_DESK_CLAUDE_BIN"] = str(_ELSEWHERE / "claude-is-never-run-by-this-suite")


def pytest_sessionfinish() -> None:
    """Take the empty tree away again, so a hundred runs are not a hundred directories."""
    shutil.rmtree(_ELSEWHERE, ignore_errors=True)
