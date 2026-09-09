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
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent_desk.ideas import inbox
from agent_desk.mcp import saying
from agent_desk.store.repo import StepState, Store

# How much of an idea's own words travel in a listing. The summary is one line by construction; this
# is for the call that asks for one idea in full.
MOST_TEXT = 2000

# The states a step can be in, in the order a reader wants them: what is finished first, what
# went wrong next, and what has not happened yet last (agent_desk/store/repo.py).
STATES: tuple[StepState, ...] = ("done", "failed", "held", "going", "waiting")


@dataclass(frozen=True)
class Tool:
    """One thing an agent can call."""

    name: str
    says: str
    # JSON Schema for the arguments, as MCP asks for it.
    takes: dict[str, Any]
    run: Callable[[Store, dict[str, Any]], Awaitable[str]]
    # One line of what comes back. "Пример ответа стоит абзаца описания: агент видит форму и не
    # пробует вызов, чтобы её узнать." Required in spirit and in `what_is_here`, which is the only
    # place it is read.
    shows: str = ""
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

    # Somebody who chose three cards gets three, and a name that is not on this bench is said
    # rather than dropped: an agent that mistyped a card and got the whole workbench back would
    # think it had asked for the whole workbench.
    names, why = await _cards_for(store, given)
    if why:
        return why
    rows, _ = await asyncio.to_thread(routes.board)
    carried = await blocks.carried_from_the_bench(store, rows, names)
    return blocks.as_one_string(carried) or "There is nothing on those cards to carry."


async def _run(store: Store, given: dict[str, Any]) -> str:
    """Start the drawing on a workbench and come straight back with its id.

    «Прогон схемы вызывается агентом и не проходит через его контекст.» This is the shape that
    makes a console worth calling rather than reading: the work happens here, in the console's own
    loop, and what crosses the pipe is an id. A caller that waited for a six-step drawing would be
    holding a context window open for four minutes to receive text it did not need.

    Nothing here runs anything. `engine.begin` writes the run down and the console's loop picks it
    up, which is also why this cannot report that it started well: it can report that it was
    accepted, and `how_it_went` reports the rest. Saying more would be reporting a status inferred
    from silence (CLAUDE.md, rule five).
    """
    from agent_desk.web import engine, routes

    names, why = await _cards_for(store, given)
    if why:
        return why
    where = await routes.where_for(store, names)
    made, refused = await engine.begin(
        store,
        names=names,
        repo_key=where[0],
        cwd=where[1],
        given=str(given.get("given", "")),
    )
    if made is None:
        return f"It did not start: {refused}"
    return (
        f"Started as {made.id}, over {len(names)} card{'' if len(names) == 1 else 's'}. "
        "Nothing here waits for it — ask how_it_went."
    )


async def _how_it_went(store: Store, given: dict[str, Any]) -> str:
    """The count, and the names of what failed. Never the answers.

    «Возвращает счёт, а не ответы: сколько прошло, сколько нет.» A run of eight steps holds eight
    answers, and handing them back would put the whole run into the context this call exists to
    keep out of it. What a caller needs to decide what to do next is how many, and which ones went
    wrong by name; the answers are `answer_from`'s, one at a time.
    """
    run_id = str(given.get("run", "")).strip()
    the_run = next((one for one in await store.runs() if one.id == run_id), None)
    if the_run is None:
        return "There is no run with that id."
    steps = await store.run_steps(run_id)
    if not steps:
        return f"{run_id} has not reached a step yet."
    counted = Counter(step.state for step in steps)
    said = [
        f"{run_id}: " + ", ".join(f"{counted[state]} {state}" for state in STATES if counted[state])
    ]
    failed = [step.name for step in steps if step.state == "failed"]
    if failed:
        said.append("failed: " + ", ".join(failed))
    if the_run.stopped_why:
        said.append(f"stopped: {the_run.stopped_why}")
    elif the_run.finished_at is None:
        # Not "running": a run whose console is not up sits here untouched, and this call cannot
        # tell that from one being worked on (CLAUDE.md, rule five).
        said.append("not finished")
    return "\n".join(said)


async def _answer_from(store: Store, given: dict[str, Any]) -> str:
    """One step's answer, by name.

    «Ответы прогона лежат в консоли и открываются человеком — агент берёт их поимённо.» There is
    deliberately no call that returns all of them: a caller that names the step it needs has read
    `how_it_went` and decided, and a caller that did not should not be handed eight answers to
    find out which one it wanted.
    """
    run_id = str(given.get("run", "")).strip()
    want = str(given.get("step", "")).strip()
    steps = await store.run_steps(run_id)
    if not steps:
        return "There is no run with that id, or it has not reached a step yet."
    step = next((one for one in steps if one.name == want), None)
    if step is None:
        return "That run has no step called that. Its steps: " + ", ".join(
            one.name for one in steps
        )
    if not step.made:
        return f"{want} is {step.state} and has said nothing yet." + (
            f" {step.detail}" if step.detail else ""
        )
    return step.made


async def _cards_for(store: Store, given: dict[str, Any]) -> tuple[list[str], str]:
    """Which cards a call is about: a workbench, narrowed by names when it named any."""
    thread_id, why = await _which_bench(store, str(given.get("name", "")).strip())
    if why:
        return [], why
    on_it = await store.bench_cards(thread_id)
    if not on_it:
        return [], "That workbench is empty."
    wanted = [str(one).strip() for one in given.get("cards") or [] if str(one).strip()]
    missing = [one for one in wanted if one not in {card.name for card in on_it}]
    if missing:
        return [], "Not on that workbench: " + ", ".join(missing)
    return [one.name for one in on_it if not wanted or one.name in wanted], ""


# What this console has refused to do, and why, one line each (docs/08-non-goals.md). Written here
# rather than read from the file because nothing under this package opens one — and a list an agent
# reads in its first four hundred tokens is worth three attempts it does not spend on work this
# project decided against. `tests/unit/test_mcp.py` holds it level with the document.
NOT_HERE: tuple[tuple[str, str], ...] = (
    ("Orchestrating sessions", "the board watches sessions it did not start; nothing steers one"),
    ("Sending work to a busy session", "no queue picks a good moment; a human clicks send"),
    ("`tmux send-keys` into a terminal", "an interruption wearing an automation costume"),
    ("A backlog", "ideas have four states and no priority, assignee, estimate or ordering"),
    ("Writing into an observed repository", "an idea becomes a draft here, carried over by review"),
    ("Multi-user access", "one machine, one person; anything on the port can read ~/.claude"),
    ("A desktop application", "several days of packaging to render the same HTML"),
    ("Reading anything but Claude Code sessions", "each other one is a second integration"),
    ("Transcript search, diff views, tool-call browsing", "the terminal is open and better at it"),
)


async def _ask(store: Store, given: dict[str, Any]) -> str:
    """Leave a question for a person and go on with something else.

    «Агент, упёршийся в решение, которое не его, сегодня умеет одно — остановиться и ждать.» This
    is the call that makes waiting unnecessary: the question is written down where a person will
    see it, and the caller takes up whatever does not depend on the answer.

    Nothing is sent to anybody. Nothing is written into a running session's context either, which
    is why this does not touch docs/adr/0002 — the row waits, a person presses, and the asker comes
    back for it.
    """
    question = str(given.get("question", "")).strip()
    if not question:
        return "Nothing was asked: `question` was empty."
    options = [str(one).strip() for one in given.get("options") or [] if str(one).strip()]
    made = await store.ask_a_person(
        question,
        options=options,
        done=str(given.get("done", "")),
        who=str(given.get("who", "")),
    )
    where = "on the board, holding work" if options else "on the board"
    return f"Asked as {made.id}, {where}. Nothing waits — ask answer when you need it."


async def _answer(store: Store, given: dict[str, Any]) -> str:
    """The answer to one question, or the words saying there is not one yet.

    «Возвращает ответ или говорит, что его ещё нет — словами, а не пустотой.» An empty string back
    is a caller that cannot tell "nobody has answered" from "somebody answered with nothing", and
    the two mean opposite things about whether to carry on waiting.
    """
    one = await store.question(str(given.get("id", "")).strip())
    if one is None:
        return "There is no question with that id."
    if one.waiting:
        offered = ", ".join(one.choices)
        return (
            f"Nobody has answered yet. It offers: {offered}"
            if offered
            else "Nobody has answered yet."
        )
    return one.answer or "Somebody answered it with nothing at all."


async def _what_is_here(store: Store, given: dict[str, Any]) -> str:
    """Everything this surface does, in one answer, with what each call gives back.

    «Инструмент, о котором надо прочитать документацию, — инструмент, которым не пользуются.» Not
    documentation: an answer short enough to read at the start of a piece of work, after which a
    caller knows which of its habits are unnecessary here.

    The refusals are in it for the same reason. A caller that reads them first does not spend three
    attempts on work this project decided against, and "no" with a reason attached is a shorter
    read than the three failures it prevents.
    """
    said = [f"{len(TOOLS) - 1} calls, and what each gives back.", ""]
    for one in TOOLS:
        if one.name == "what_is_here":
            continue
        said += [f"{one.name} — {one.says}", f"  → {one.shows}"]
    said += ["", "What this console will not do, and why (docs/08-non-goals.md):"]
    said += [f"- {what}: {why}" for what, why in NOT_HERE]
    return "\n".join(said)


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
        shows="Written down as 01M22F… — read the registry before the transcript",
    ),
    Tool(
        name="open_ideas",
        says="Every idea still open, one line each: id, state, summary.",
        takes={"type": "object", "properties": {}},
        run=_open_ideas,
        shows="01M22F… [new] read the registry before the transcript",
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
        shows="01M22F… [new] read the registry before the transcript — then its whole text",
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
        shows="01M22F… is done: commit b35ef0e",
    ),
    Tool(
        name="bench",
        says=(
            "A workbench as the text a question would carry: the cards, in order, saying what "
            "they say. Name a chat to get its bench, or nothing for the one outside the chats. "
            "Name cards to get only those."
        ),
        shows="## The workbench / These 3 cards are on the workbench in front of the person…",
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
    Tool(
        name="run",
        says=(
            "Run the drawing on a workbench and come straight back with a run id. Nothing waits: "
            "the console does the work and how_it_went reports it."
        ),
        shows="Started as 01M22G…, over 2 cards. Nothing here waits for it — ask how_it_went.",
        takes={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "the chat whose workbench this is"},
                "cards": {"type": "array", "items": {"type": "string"}},
                "given": {"type": "string", "description": "what the drawing is run against"},
            },
        },
        run=_run,
        writes=True,
    ),
    Tool(
        name="how_it_went",
        says="How a run stands: how many steps done, how many failed, and which ones by name.",
        takes={
            "type": "object",
            "properties": {"run": {"type": "string"}},
            "required": ["run"],
        },
        run=_how_it_went,
        shows="01M22G…: 2 done, 1 failed / failed: step:rewrite",
    ),
    Tool(
        name="answer_from",
        says="What one step of a run said, by name. There is no call that returns all of them.",
        takes={
            "type": "object",
            "properties": {"run": {"type": "string"}, "step": {"type": "string"}},
            "required": ["run", "step"],
        },
        run=_answer_from,
        shows="…what that one step said, and nothing else…",
    ),
    Tool(
        name="ask",
        says=(
            "Leave a question for a person, with the options they can press, and carry on. "
            "It waits on the board as something holding work."
        ),
        takes={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "what they can press; a question with none is answered in words",
                },
                "done": {"type": "string", "description": "what is already built and waiting"},
                "who": {"type": "string", "description": "who is asking"},
            },
            "required": ["question"],
        },
        run=_ask,
        writes=True,
        shows="Asked as 01M22H…, on the board, holding work. Nothing waits — ask answer…",
    ),
    Tool(
        name="answer",
        says="What somebody pressed on a question, or the words saying nobody has yet.",
        takes={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
        run=_answer,
        shows="Nobody has answered yet. It offers: keep the column, drop it",
    ),
    Tool(
        name="what_is_here",
        says="Everything this console can be asked, and what it has decided not to do.",
        takes={"type": "object", "properties": {}},
        run=_what_is_here,
        shows="8 calls, and what each gives back. …",
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
