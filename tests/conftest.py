"""What the whole suite runs under, before anything imports `agent_desk.config`.

The CLI this program starts is resolved from PATH, and on the machine this suite usually runs on it
is there. So a test that reached `dispatch.start` without faking it started a real `claude --bg`
agent — in a worktree of whichever checkout ran the gate — and a test that reached the answer
engine spent a real `claude -p` call. The Stop hook runs the gate at every turn end, which made
that one agent, named after the test's input, every few minutes: fifty-four of them told only
"бери в работу" in one day, each with nothing in front of it to act on (docs/adr/0006 — an agent
is started by a click, never by a background loop).

A name that resolves to nothing turns every such path into the one it already handles: the CLI is
not installed here. A test that wants a CLI builds its own `Settings(claude_bin=...)`.
"""

from __future__ import annotations

import os

os.environ["AGENT_DESK_CLAUDE_BIN"] = "claude-is-never-run-by-this-suite"
