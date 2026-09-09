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

import asyncio
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


async def _bench(store: Store, given: dict[str, Any]) -> str:
    """A workbench as assembled context, not as a page.

    "Верстак — это конструктор контекста, и человек уже собрал его руками." The cheapest thing this
    console can give an agent is the arrangement somebody already made: which cards, in which
    order, saying what, with which files allowed. It costs nothing to produce because the console
    builds this text every time somebody presses send.

    What comes back is that text and not a description of it — the same section a question carries,
    built by the prompt's own writers (`agent_desk/answer/session.py`). An agent handed a summary
    of a workbench would be reading somebody's notes about the work instead of the work.

    Two limits are inherited rather than restated here, which is the point of gathering it in one
    function. A file contributes its contents only where somebody said it may (055), so an agent
    sees exactly what is on the screen and never a file the person themselves has not opened; and
    everything is scrubbed on the way out.
    """
    # Late because the board is the console's and importing it at module load would drag a web
    # application into a program that speaks on a pipe.
    from agent_desk.web import blocks, routes

    name = str(given.get("name", "")).strip()
    thread_id, why = await _which_bench(store, name)
    if why:
        return why
    on_it = await store.bench_cards(thread_id)
    if not on_it:
        return "That workbench is empty."
    wanted = [str(one).strip() for one in given.get("cards") or [] if str(one).strip()]
    cards = [one for one in on_it if not wanted or one.name in wanted]
    # Somebody who chose three cards gets three. A name that is not on this bench is said rather
    # than dropped: an agent that mistyped a card and got the whole workbench back would think it
    # had asked for the whole workbench.
    missing = [one for one in wanted if one not in {card.name for card in on_it}]
    if missing:
        return "Not on that workbench: " + ", ".join(missing)
    rows, _ = await asyncio.to_thread(routes.board)
    carried = await blocks.carried_from_the_bench(store, rows, [card.name for card in cards])
    return blocks.as_one_string(carried) or "There is nothing on those cards to carry."


async def _which_bench(store: Store, name: str) -> tuple[str, str]:
    """Which chat's workbench that is: the id, or the sentence saying why there is none.

    No name means the workbench that belongs to no chat, which is the one somebody opens the
    console to. A name is matched against what the chats are called, because that is what is
    written on the tab and the only name a person has for a bench.
    """
    if not name:
        return "", ""
    open_ = await store.open_threads()
    for one in open_:
        if one.subject.strip().lower() == name.lower():
            return one.id, ""
    called = ", ".join(one.subject for one in open_) or "none are open"
    return "", f"No workbench is called {name!r}. Open chats: {called}."


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
    Tool(
        name="bench",
        says=(
            "A workbench as the text a question would carry: the cards, in order, saying what "
            "they say. Name a chat to get its bench, or nothing for the one outside the chats. "
            "Name cards to get only those."
        ),
        takes={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "the chat whose workbench this is"},
                "cards": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "card names, `kind:id`, when only some of them are wanted",
                },
            },
        },
        run=_bench,
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
