"""The shape of what this server says back, and the rule about how much of it.

*«Каждый ответ агенту помещается в контекст, и то, что не влезло, называется числом.»*

An instrument that can return a page of text is one that will eventually eat half of somebody's
context window. A hard ceiling turns a call from a risk into a decision — and the tail that says how
much was left turns a truncated answer from a lie into a fact with a number attached.

Pure: text in, text out. Nothing here talks to a store or a socket.
"""

from __future__ import annotations

# One ceiling for the whole surface. Per-tool ceilings would be six numbers to keep in step, and
# the day two of them disagree is the day an agent's context depends on which call it made.
MOST_CHARS = 4000

# How a truncated answer ends. It names the unit that was cut so the reader knows what "more" would
# get them — lines, not bytes, because lines are what the caller asked for.
MORE = "\n… and {left} more line{s}. Ask for the ones you need by name."


def within(said: str, *, most: int = MOST_CHARS) -> str:
    """`said`, cut to fit, with what was cut named rather than dropped.

    Cut on a line boundary: half a line is a fact somebody may act on, and the second half of a
    sentence is worse than an honest count. A single line longer than the whole budget is cut where
    it must be, because refusing it outright would answer nothing at all.
    """
    if len(said) <= most:
        return said
    lines = said.splitlines()
    kept: list[str] = []
    room = most - len(MORE.format(left=len(lines), s="s"))
    used = 0
    for line in lines:
        if used + len(line) + 1 > room:
            break
        kept.append(line)
        used += len(line) + 1
    left = len(lines) - len(kept)
    if not kept:
        # One line and no room for it. Cut it rather than answer nothing: an instrument that
        # returns nothing when asked something is one nobody calls twice.
        return said[: max(0, room)] + MORE.format(left=left, s="s" if left != 1 else "")
    return "\n".join(kept) + MORE.format(left=left, s="s" if left != 1 else "")
