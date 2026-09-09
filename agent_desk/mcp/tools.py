"""What an agent may call, and what each call answers.

*«Возможность подключаться к этому проекту по MCP.»*

## Why the pool is the first thing here

This program's stated purpose is "an idea inbox that costs no agent any context" (CLAUDE.md). Until
now only a person could write into it. An agent that can record a thought, list what is open and
close one has stopped holding its list of things to do in a context window — which is the list it
loses at every compaction.

## Nothing here removes anything

There is no call that deletes. The worst a mistaken agent can do is add a row to a list, and that is
what makes this surface safe to call without asking first. Deleting stays a person's, on the page,
where undo is.

## What comes back is text, and it is bounded

Every answer goes through `saying.within`. A tool that can return the whole pool is one that will
one day return the whole pool into somebody's context window.

Pure-ish: these take a store and return text. The protocol is `server.py`'s and knows nothing about
what any of this means.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent_desk.ideas import inbox
from agent_desk.mcp import saying
from agent_desk.store.repo import Store

# How much of an idea's own words travel in a listing. The summary is one line by construction; this
# is for the call that asks for one idea in full.
MOST_TEXT = 2000


@dataclass(frozen=True)
class Tool:
    """One thing an agent can call."""

    name: str
    says: str
    # JSON Schema for the arguments, as MCP asks for it.
    takes: dict[str, Any]
    run: Callable[[Store, dict[str, Any]], Awaitable[str]]
    # Whether calling it changes anything. Said out loud because a caller deciding whether to ask
    # first deserves to know, and because a surface where that is obvious per tool cannot grow a
    # destructive one by accident.
    writes: bool = False
    aliases: tuple[str, ...] = field(default_factory=tuple)


def _text(said: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": saying.within(said)}]}


async def _keep(store: Store, given: dict[str, Any]) -> str:
    """Record a thought. Twice with the same words is one idea, not two.

    An agent that was restarted mid-task and writes its list again should not double the pool, and
    it has no way of knowing whether the first attempt landed.
    """
    text = str(given.get("text", "")).strip()
    if not text:
        return "Nothing was written down: `text` was empty."
    for one in await store.ideas():
        if one.text.strip() == text:
            return f"Already here as {one.id}: {one.summary}"
    try:
        made = await inbox.capture(store, text, author="desk")
    except ValueError as why:
        # An idea written by an agent is a proposal, and a proposal arrives with nobody: if its
        # first line cannot be understood without opening the card, the work of getting into its
        # context has been handed to whoever reads it — which is the work it was meant to save
        # (039-idea-author.sql). Said in full rather than as a failure, because the fix is one
        # sentence and the caller is the one who can write it.
        return f"Not written down. {why}"
    return f"Written down as {made.id}: {made.summary}"


async def _open_ideas(store: Store, given: dict[str, Any]) -> str:
    """Everything still open, one line each: id, state, and the summary.

    Lines rather than objects. What a caller does with this is read it, and a JSON array of
    objects costs three times the tokens to say the same thing.
    """
    rows = [one for one in await store.ideas() if one.state in ("new", "kept", "promoted")]
    if not rows:
        return "Nothing is open."
    return "\n".join(f"{one.id} [{one.state}] {one.summary}" for one in rows)


async def _idea(store: Store, given: dict[str, Any]) -> str:
    """One idea in full: what was written, and what has become of it."""
    one = await store.idea(str(given.get("id", "")).strip())
    if one is None:
        return "There is no idea with that id."
    said = [f"{one.id} [{one.state}] {one.summary}", "", one.text[:MOST_TEXT]]
    if one.parent_id:
        said += ["", f"part of {one.parent_id}"]
    return "\n".join(said)


async def _close(store: Store, given: dict[str, Any]) -> str:
    """Mark an idea built, with a note saying by what.

    The note is not optional in spirit: an idea closed with nothing pointing at what closed it is a
    row that says work happened and cannot show it.
    """
    idea_id = str(given.get("id", "")).strip()
    one = await store.idea(idea_id)
    if one is None:
        return "There is no idea with that id."
    note = str(given.get("note", "")).strip()
    if not note:
        return "Say what closed it — a commit, a file, a sentence."
    await store.set_idea_state(idea_id, "done")
    await store.say_card(f"idea:{idea_id}", f"built — {note}", one.text[:400])
    return f"{idea_id} is done: {note}"


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="keep_idea",
        says="Write a thought into the idea pool. The same text twice is one idea, not two.",
        takes={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "the thought, in full"}},
            "required": ["text"],
        },
        run=_keep,
        writes=True,
    ),
    Tool(
        name="open_ideas",
        says="Every idea still open, one line each: id, state, summary.",
        takes={"type": "object", "properties": {}},
        run=_open_ideas,
    ),
    Tool(
        name="idea",
        says="One idea in full, by id.",
        takes={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
        run=_idea,
    ),
    Tool(
        name="close_idea",
        says="Mark an idea built, with a note saying what closed it.",
        takes={
            "type": "object",
            "properties": {"id": {"type": "string"}, "note": {"type": "string"}},
            "required": ["id", "note"],
        },
        run=_close,
        writes=True,
    ),
)


def named(name: str) -> Tool | None:
    return next((one for one in TOOLS if one.name == name), None)


async def call(store: Store, name: str, given: dict[str, Any]) -> dict[str, Any]:
    """Run one tool and shape what it said the way MCP asks for it.

    A tool that raises is answered as text rather than as a protocol error: a caller that asked for
    something reasonable and got a transport failure has no way to tell that from the server being
    down, and this server's whole promise is that calling it is cheap and safe.
    """
    tool = named(name)
    if tool is None:
        return _text(f"There is no tool called {name}. Ask for tools/list.")
    try:
        return _text(await tool.run(store, given))
    # A tool that raises is answered as text rather than as a protocol error.
    except Exception as why:
        return _text(f"That did not work: {type(why).__name__}: {why}")
