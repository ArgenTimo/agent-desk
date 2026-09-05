"""The tail of one session's transcript.

Two rules from docs/03-session-observation.md shape this module:

**Find the file by globbing `*/<sessionId>.jsonl`.** The directory name is a lossy transform of
`cwd` — separators and spaces map to the same character — so it cannot be inverted, and two
working directories can collide in it. The session id is unique and the glob is one call.

**Read the tail, not the file.** These reach tens of megabytes. The reader seeks from the end and
stops after a bounded window.

Sidechains are skipped: a subagent's tool calls are noise on a board whose job is to say what the
*session* is doing.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_desk.config import settings
from agent_desk.observe.model import AgentCall, TailEntry, TranscriptTail

# A session id reaches this module from a URL path, and it is interpolated into a glob. Anything
# that is not a session id is not sanitised into one — it is refused.
_SESSION_ID = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")

# One entry is rendered on a board row, and a human pasted a file into some of them. The cap is a
# display decision and it is here rather than in a template because the template is not the place
# a megabyte should already have reached.
_MAX_ENTRY_CHARS = 2000


def _find(session_id: str, root: Path) -> Path | None:
    """`~/.claude/projects/*/<sessionId>.jsonl`, never a slug derived from `cwd`.

    A session id resumed in a second directory can produce two files; the most recently written
    one is the one the session is appending to.
    """
    if not _SESSION_ID.match(session_id):
        return None
    matches = list(root.glob(f"*/{session_id}.jsonl"))
    if not matches:
        return None

    def written_at(path: Path) -> float:
        # The file can be removed between the glob and the question; a session that ended while
        # the board was drawing is not an error worth propagating into the stream.
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return max(matches, key=written_at)


def _tail_window(path: Path, max_bytes: int) -> list[str]:
    """Complete lines from the last `max_bytes` of the file, oldest first.

    The first line of the window is dropped unless the read reached the start of the file: it is
    the tail of a line whose beginning was not read. Decoding is lenient for the same reason — the
    window boundary can fall inside a multi-byte character, and that character is in the fragment
    being discarded.
    """
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        start = max(0, size - max_bytes)
        handle.seek(start)
        window = handle.read(size - start)

    lines = window.decode("utf-8", errors="replace").splitlines()
    return lines[1:] if start > 0 and lines else lines


def _at(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _flatten(message: Any) -> str:
    """A content list, rendered as one line of text.

    A tool call contributes its name and not its input. "The last action taken" is answered by
    `Bash`; the command itself is the terminal's business, and this program's job is to say
    whether to go and look (docs/06-console.md).
    """
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()[:_MAX_ENTRY_CHARS]

    parts: list[str] = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"].strip())
        elif kind == "tool_use":
            parts.append(f"[{block.get('name', 'tool')}]")
        elif kind == "tool_result":
            parts.append("[tool result]")
        else:
            parts.append(f"[{kind}]")
    return " ".join(p for p in parts if p)[:_MAX_ENTRY_CHARS]


def _context_tokens(message: Any) -> int | None:
    """How much this turn was carrying, from the usage the CLI writes on an assistant message.

    Input plus both cache halves: what the model was handed. The output is deliberately not in it
    — the question a card answers is "how big has this session got", and the answer to that is the
    size of what goes in. A message with no usage returns None rather than nought, because a
    missing number and a zero are different facts (docs/03-session-observation.md).
    """
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    counted = [
        usage.get("input_tokens"),
        usage.get("cache_creation_input_tokens"),
        usage.get("cache_read_input_tokens"),
    ]
    numbers = [one for one in counted if isinstance(one, int)]
    return sum(numbers) if numbers else None


def _agent_calls(message: Any) -> list[tuple[str, str, str]]:
    """Every `Agent` tool call in one entry: its id, the kind of agent, and what it was asked for.

    The prompt it was given is deliberately not read. A card wants to say "Explore · inventory the
    skills", and the rest is the session's business.
    """
    content = message.get("content") if isinstance(message, dict) else None
    found = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        if block.get("name") != "Agent":
            continue
        raw = block.get("input")
        arguments: dict[str, Any] = raw if isinstance(raw, dict) else {}
        found.append(
            (
                str(block.get("id", "")),
                str(arguments.get("subagent_type") or "agent"),
                str(arguments.get("description") or "").strip(),
            )
        )
    return found


def _tool_results(message: Any) -> set[str]:
    """The ids of calls that have come back."""
    content = message.get("content") if isinstance(message, dict) else None
    return {
        str(block["tool_use_id"])
        for block in (content if isinstance(content, list) else [])
        if isinstance(block, dict) and block.get("type") == "tool_result" and "tool_use_id" in block
    }


def read_tail(
    session_id: str,
    *,
    root: Path | None = None,
    lines: int | None = None,
    max_bytes: int | None = None,
) -> TranscriptTail | None:
    """The tail of `session_id`'s transcript, or `None` when there is no file to read.

    `None` is not an error: a session that has not written a transcript yet, or one whose file is
    unreadable, shows registry facts only and the board says so
    (docs/02-architecture.md, failure posture).
    """
    root = root if root is not None else settings.transcripts_root
    lines = lines if lines is not None else settings.transcript_tail_lines
    max_bytes = max_bytes if max_bytes is not None else settings.transcript_tail_bytes

    path = _find(session_id, root)
    if path is None:
        return None
    try:
        window = _tail_window(path, max_bytes)
    except OSError:
        return None

    title: str | None = None
    last_prompt: str | None = None
    git_branch: str | None = None
    entries: list[TailEntry] = []
    # A subagent is two lines apart: the call that started it and the result that ended it, so
    # both halves are collected and matched once the window has been read.
    calls: list[tuple[str, str, str]] = []
    returned: set[str] = set()
    context_tokens: int | None = None

    for raw in window:
        try:
            line = json.loads(raw)
        except ValueError:
            # A line torn by a write in progress, or the tail of one older than the window. Not a
            # format change and not worth a notice: the next read gets it whole.
            continue
        if not isinstance(line, dict) or line.get("isSidechain"):
            continue

        kind = line.get("type")
        if kind == "ai-title":
            title = line.get("aiTitle") or title
        elif kind == "last-prompt":
            last_prompt = line.get("lastPrompt") or last_prompt
        elif kind in ("user", "assistant"):
            # gitBranch is what makes the board legible across worktrees of one repository.
            git_branch = line.get("gitBranch") or git_branch
            context_tokens = _context_tokens(line.get("message")) or context_tokens
            calls.extend(_agent_calls(line.get("message")))
            returned.update(_tool_results(line.get("message")))
            entries.append(
                TailEntry(
                    role=kind, text=_flatten(line.get("message")), at=_at(line.get("timestamp"))
                )
            )

    if title is None and last_prompt is None and not entries:
        # The file exists and the window yielded nothing readable. Returning an empty tail here
        # would render a row of em-dashes that looks like a quiet session; returning None marks it
        # as unread, which is what it is (docs/02-architecture.md, failure posture).
        return None

    return TranscriptTail(
        session_id=session_id,
        title=title,
        last_prompt=last_prompt,
        git_branch=git_branch,
        context_tokens=context_tokens,
        entries=entries[-lines:],
        # Most recent first, which is the order a card reads them in.
        agents=[
            AgentCall(kind=kind, description=description, finished=call_id in returned)
            for call_id, kind, description in reversed(calls)
        ],
    )
