"""Running a drawing: one step at a time, in the order the lines describe.

*"Под капотом контекст + агент + тулзы + пермишены + память + конкретное выполнение по порядку,
то есть движок."* Everything before this described a process. This is the part that does one.

## It queues; it does not start

That is the single decision this module is built around, and it is what makes an engine safe to
add to this program rather than a second program bolted onto it.

The console already knows how to start work, and it knows it carefully: a project has to be armed,
only one agent runs in it at a time, there is an hour's budget, and two failures in a row switch
the project off (`agent_desk/web/autostart.py`, docs/adr/0007). An engine that called
`dispatch.start` itself would be outside every one of those, and the first thing anybody would
notice is a drawing with nine steps starting nine agents at three in the morning.

So a step becomes a **queued task**, exactly the way "build it" and a deferred idea do, and the
loop that already exists starts it under the rules that already exist. This module's whole job is
sequencing: put the next step in the queue when the last one is finished, and carry what it
produced forward.

## What each kind of step actually does

- **Action** — a task in the queue, briefed with its own fields and with what the steps leading
  into it produced (`agent_desk/process.py`). Unless it is read-only, in which case there is no
  agent and no worktree at all: it is asked, and the answer is what it produced. That is the
  `read` permission being enforced rather than described (`agent_desk/allowed.py`).
- **Decision** — always asked, never given an agent: a decision does not write anything. It is
  given its question and the conditions on the lines going out of it, and answers with which one.
  The same shape as every other model call in this program — a numbered list and one token back
  (`agent_desk/answer/classify.py`) — because free text matched against branch labels is a guess
  wearing a mechanism.
- **Event** — waits. It is the one step that is not work: something has to happen, and until
  somebody says it has, the run is held. Held is not failed and the difference is kept, because a
  run waiting on Tuesday's release is a run that is fine.

## Where a run can stop

A step that fails stops the run and the run says which step and why. It does not skip ahead: the
steps after it were described on the assumption that it worked, and running them anyway is how a
process produces confident wrong output. Retrying is a human pressing something, which is the same
rule the failed-task blocker follows.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import structlog

from agent_desk import allowed, dispatch, land, process, roles
from agent_desk.answer.session import AnswerFailed, stream_answer
from agent_desk.store.repo import Run, RunStep, Store
from agent_desk.web import autostart, blockers

log = structlog.get_logger()

# How often a run is looked at. The same deliberate slowness as the other loops: a step that has
# been finished for thirty seconds is not more urgent than one finished for ten, and every tick
# costs a registry read.
TICK_SECONDS = 20.0

# How much of an answer is kept as what a step produced. Enough to be the input to the next step,
# bounded so that one talkative step cannot fill the briefing of every step after it.
MOST_MADE = 4000


async def bench_of(store: Store, names: list[str]) -> list[process.Card]:
    """The cards of a run, as the process reader needs them."""
    chosen = await store.card_roles()
    said = await store.card_fields()
    made = await store.cards_made()
    labels = {f"idea:{one.id}": one.summary for one in await store.ideas(limit=400)}
    # A step card's name is the one thing it holds that is its own, and a run whose steps were all
    # called "step:01M…" would be a run nobody can read.
    labels |= {one.name: one.label for one in await store.step_cards()}
    return [
        process.Card(
            name=name,
            role=roles.role_of(name.split(":", 1)[0], chosen.get(name, "")).name,
            label=labels.get(name, name),
            said=said.get(name, {}),
            made=made.get(name, ""),
        )
        for name in names
    ]


async def lines_of(store: Store, names: list[str]) -> list[process.Line]:
    here = set(names)
    return [
        process.Line(from_name=tie.from_name, to_name=tie.to_name, kind=tie.kind, says=tie.says)
        for tie in await store.card_ties()
        if tie.from_name in here and tie.to_name in here
    ]


async def begin(
    store: Store, *, names: list[str], repo_key: str, cwd: str, given: str = ""
) -> tuple[Run | None, str]:
    """Start a run of this drawing, or say why not.

    The refusal comes from `process.ready_to_run`, which is the same function the panel shows —
    so a button that is offered and a run that is refused cannot disagree about why.

    `given` is what somebody typed to start it, which the steps can then read (057). A pipeline is
    a shape run more than once with different inputs, so the input belongs to the run.
    """
    cards = await bench_of(store, names)
    why = process.ready_to_run(cards, await lines_of(store, names))
    if why:
        return None, why
    # A drawing made only of prompts needs no project and no checkout: it does not touch either,
    # which is what its permission means rather than describes. Asking for one would be asking
    # where to run something that runs nowhere (01M1X8DA8REGR836D77PPV3W54).
    if not all_prompts(cards) and (not repo_key or not cwd):
        return (
            None,
            "there is nowhere to run this: the cards are not about a project with a checkout",
        )
    run = await store.start_run(cards=names, repo_key=repo_key, cwd=cwd, given=given)
    log.info("engine.began", run=run.id, steps=len(names))
    return run, ""


def all_prompts(cards: list[process.Card]) -> bool:
    """Whether every step of this drawing is a prompt, and it therefore touches nothing."""
    steps = [card for card in cards if card.role in process.STEPS]
    return bool(steps) and all(allowed.is_a_prompt(card.said) for card in steps)


def _next_step(
    run: Run, cards: list[process.Card], lines: list[process.Line], done: dict[str, RunStep]
) -> str:
    """The next step to do: the first in the order that is a step and is not finished.

    Order comes from the lines, never from the order cards were put on the bench — "порядок
    берётся из связей, а не из того, в каком порядке карточки положили на верстак".
    """
    by_name = {card.name: card for card in cards}
    for name in process.order(cards, lines).steps:
        card = by_name.get(name)
        if card is None or card.role not in process.STEPS:
            continue
        step = done.get(name)
        if step is None or step.state in ("waiting", "going", "held"):
            return name
    return ""


def briefing(name: str, cards: list[process.Card], lines: list[process.Line]) -> str:
    """What this step is told: what it has to do, and what led into it.

    Its own words first. A briefing that opened with three paragraphs of what other steps produced
    and reached the instruction last would be one an agent skims.
    """
    card = next((one for one in cards if one.name == name), None)
    if card is None:
        return ""
    said = []
    for field in roles.fields_of(card.role):
        words = (card.said.get(field.name) or "").strip()
        if words:
            said.append(f"{field.says}: {words}")
    memory = process.memory_for(name, cards, lines)
    if memory:
        said.append("")
        said.append(memory)
    return "\n".join(said)


def _permission_words(given: tuple[str, ...]) -> list[str]:
    """The permissions as a note in the briefing.

    Every one of these is *also* enforced somewhere else, except `net`. They are said here as well
    because an agent that knows it may not push will not spend a turn trying, and because a
    briefing that silently differs from what the console will allow is how an agent ends up
    reporting work it was not permitted to keep.
    """
    said = [f"You may {allowed.ALLOWED[one].means}." for one in given]
    if "land" not in given:
        said.append("Do not merge anything: this step's branch is not being offered to the gate.")
    if "push" not in given:
        said.append("Do not push.")
    if "net" not in given:
        said.append("Work from what is already here rather than fetching anything.")
    return said


async def _ask(prompt: str) -> tuple[str, str]:
    """Ask, and give back what came back. Never raises: a step that could not be asked is a step
    that failed, and the run says so rather than the loop falling over."""
    try:
        return "".join([chunk async for chunk in stream_answer(prompt)]).strip(), ""
    except (AnswerFailed, OSError) as gone:
        return "", str(gone)[:300]


def branch_prompt(
    card: process.Card,
    ways: list[process.Line],
    *,
    memory: str = "",
    known: Sequence[str] = (),
) -> str:
    """The question a Decision is asked, as a numbered list with one token back.

    The same shape as every other model call here (`agent_desk/answer/classify.py`), and for the
    same reason: free text matched against branch labels is a guess wearing a mechanism.

    "Развилка «прошёл ли гейт» сегодня отвечает по тому, что написано на карточке, — то есть по
    описанию, а не по факту… Иначе развилки в схеме — это развилки по мнению модели о том, что,
    вероятно, произошло."

    So two things arrive that did not before. `memory` is what the steps leading into this one
    actually produced — the branch after "run the tests" could not see what the tests said, which
    is the whole of what it was being asked about. `known` is what this console has *read*: which
    of this project's work is running, what failed, what is blocking it.

    Both are labelled as read rather than reasoned, and the prompt says outright that a decision
    contradicting them is wrong. That instruction is the difference between giving a model facts
    and giving it atmosphere.
    """
    lines = [
        "A process has reached a decision. Answer with the number of the way it should go, then a",
        "few words saying what decided it. Nothing else: no preamble, no closing line.",
        "",
        "  2 the tests came back red, so it cannot go out",
        "",
        "The number first and on its own is what makes this readable at all — but a branch with no",
        "reason beside it is the thing nobody can argue with later, and 'why did it go that way'",
        "is exactly the question asked when a run goes somewhere unexpected.",
        "",
        f"## What has to be decided\n{(card.said.get('ask') or '').strip()}",
        "",
        "## The ways out",
    ]
    lines += [f"{index}. {one.says or 'unlabelled'}" for index, one in enumerate(ways, start=1)]
    if card.made.strip():
        lines += ["", "## What this step itself produced", card.made.strip()]
    if memory.strip():
        lines += ["", "## What the steps before it produced", memory.strip()]
    if known:
        lines += [
            "",
            "## What this console has read off disk",
            "Facts, not opinions: this is the state of the work itself. Where one of these settles",
            "the question, it settles it — a decision that contradicts what is written here is",
            "wrong however reasonable it sounds.",
            *known,
        ]
    return "\n".join(lines)


def read_why(reply: str) -> str:
    """What the reply gave as its reason, or an empty string.

    "Сейчас остаётся «пошёл туда-то». Не остаётся, на основании чего — а это ровно тот вопрос,
    который зададут, когда прогон пойдёт не туда."

    Absent is a real answer and reads as one: a decision recorded with no reason says the model
    did not give one, which is a different thing from a reason nobody wrote down. Nothing is
    invented to fill the gap — that is the guess the fifth rule forbids, and it would be the worst
    possible place for one, because a made-up reason beside a real branch is indistinguishable
    from a real one.
    """
    said = reply.strip().split(maxsplit=1)
    if len(said) < 2:
        return ""
    return " ".join(said[1].split())[:WHY_CHARS].strip(" -—:.")


# How much of a reason is kept. It sits on a card and in a run's history, where it is read at a
# glance beside the branch it explains rather than opened and studied.
WHY_CHARS = 160


def read_branch(reply: str, count: int) -> int:
    """The number the reply names, or 0 when it named nothing usable.

    Zero is a real answer and means "it did not decide", which holds the run rather than picking a
    branch at random — the failure this refuses is a process that took the first way out because
    the model said something conversational.
    """
    said = reply.strip().split()
    if not said:
        return 0
    first = said[0].strip(".,:;!?\"'")
    return int(first) if first.isdigit() and 1 <= int(first) <= count else 0


async def tick(store: Store) -> int:
    """Move every run on by whatever it can. Returns how many steps changed state.

    A run is looked at once per tick and moves at most one step: sequencing is the whole point,
    and a tick that raced ahead through four steps because three of them were quick would be a
    tick that ignored the order it was given.
    """
    moved = 0
    for run in await store.runs(going=True):
        try:
            moved += await _one(store, run)
        except Exception:
            # A run that cannot be advanced is stopped and says so, rather than being retried for
            # ever by a loop that logs the same exception every twenty seconds.
            log.exception("engine.run_failed", run=run.id)
            await store.end_run(run.id, why="something went wrong advancing this run")
    return moved


async def _one(store: Store, run: Run) -> int:
    names = run.names
    cards = await bench_of(store, names)
    lines = await lines_of(store, names)
    done = {step.name: step for step in await store.run_steps(run.id)}
    by_name = {card.name: card for card in cards}

    name = _next_step(run, cards, lines, done)
    if not name:
        await store.end_run(run.id)
        log.info("engine.finished", run=run.id)
        return 1

    card = by_name[name]
    step = done.get(name)
    if run.at != name:
        await store.run_at(run.id, name)

    # Already going: see whether whatever is doing it has finished.
    if step is not None and step.state == "going":
        return await _settle(store, run, card, step)

    if card.role == "event":
        return await _wait_for(store, run, card, step)
    if card.role == "decision":
        return await _decide(store, run, card, cards, lines)
    return await _do(store, run, card, cards, lines)


async def _do(
    store: Store,
    run: Run,
    card: process.Card,
    cards: list[process.Card],
    lines: list[process.Line],
) -> int:
    """An Action: a whole process of its own, asked when it is read-only, queued when it is not."""
    inside = (card.said.get("runs") or "").strip()
    if inside:
        return await _run_a_process(store, run, card, inside)
    # A step whose work is a prompt may only read, and that is not the default it starts at — it
    # is what the step is. Read here rather than trusted from the switches, because a switch is a
    # thing somebody can move and this one may not be moved (agent_desk/allowed.py).
    given = (
        allowed.leave_for_a_prompt()
        if allowed.is_a_prompt(card.said)
        else allowed.leave_for((await store.card_leaves()).get(card.name))
    )
    # A step whose work is a prompt sends that prompt, not a briefing written about it. The
    # briefing exists to turn a drawn process into instructions for an agent; a pipeline step is
    # the prompt somebody is testing, and wrapping it in a paragraph about the diagram would be
    # testing something else (01M1X8DA8REGR836D77PPV3W54).
    said = _asking(card, run.given, await _what_is_known(store, run)) or briefing(
        card.name, cards, lines
    )

    if allowed.reads_only(given):
        # No worktree and no agent at all, which is what the `read` permission means rather than
        # describes (agent_desk/allowed.py).
        answer, gone = await _ask(said)
        if gone:
            await store.set_run_step(run_id=run.id, name=card.name, state="failed", detail=gone)
            await store.end_run(run.id, why=f"{card.label or card.name}: {gone}")
            return 1
        await store.card_made(card.name, answer[:MOST_MADE])
        await store.set_run_step(
            run_id=run.id, name=card.name, state="done", made=answer[:MOST_MADE]
        )
        return 1

    task = await store.queue_task(
        repo_key=run.repo_key,
        cwd=run.cwd,
        title=(card.label or card.name)[:60],
        instruction=dispatch.build_task(
            said,
            project=card.label or card.name,
            notes=_permission_words(given),
            **await autostart.about(store, run.repo_key),  # type: ignore[arg-type]
        ),
        source_kind="step",
        # Which run and which step this is, so the tick that finds the finished task knows what to
        # write it against.
        source_ref=f"{run.id}|{card.name}",
    )
    await store.set_run_step(
        run_id=run.id, name=card.name, state="going", task_id=task.id, detail="queued"
    )
    log.info("engine.queued", run=run.id, step=card.name, task=task.id)
    return 1


def _asking(card: process.Card, given: str, known: list[str]) -> str:
    """The prompt this step sends, or "" when it is not that kind of step.

    Three parts, in the order they matter. The prompt somebody wrote, verbatim and first, because
    it is the thing being tested and anything above it is something else being tested. Then what
    this run was given — the words typed to start it, the same shape run against a different input
    being the point of building one. Then what came out of the steps before it, because a pipeline
    is steps that feed each other and a step that could not see the last answer is a step in a
    different pipeline.

    What the answer should look like is deliberately not a field of its own. Anybody writing a
    prompt says "answer with one line" inside it, and a second box for that is a second place for
    the same sentence to be — wrong the first time they disagree.
    """
    asks = (card.said.get("asks") or "").strip()
    if not asks:
        return ""
    lines = [asks]
    if given.strip():
        lines += ["", "## What this run was given", given.strip()]
    if known:
        lines += ["", "## What the steps before this one produced", *known]
    return "\n".join(lines)


async def _run_a_process(store: Store, run: Run, card: process.Card, name: str) -> int:
    """A step whose work is a saved drawing (049-a-step-that-is-a-process.sql).

    "Иначе конструктор упирается в потолок примерно на десяти шагах, а все интересные процессы
    длиннее."

    The nested run is an ordinary run — same steps, same states, same engine, same undo — and the
    only thing it carries extra is where to report back to. That is why this needed no new state:
    `going` already means "started, and waiting for the thing it started", which is exactly what
    the outer step is doing.
    """
    made = next((one for one in await store.templates() if one.name == name), None)
    if made is None:
        why = f"there is no saved process called “{name}”"
        await store.set_run_step(run_id=run.id, name=card.name, state="failed", detail=why)
        await store.end_run(run.id, why=f"{card.label or card.name}: {why}")
        return 1
    # Its own cards, for the reason a template always makes new ones: a process run twice must not
    # overwrite what the first time produced.
    fresh: dict[int, str] = {}
    for step in made.steps:
        inner = await store.add_step_card(step.label)
        fresh[step.ord] = inner.name
        await store.set_card_role(inner.name, step.role)
        for asked, value in step.fields.items():
            if roles.is_a_field(step.role, asked):
                await store.set_card_field(inner.name, asked, value)
        if step.leave:
            await store.set_card_leave(inner.name, list(step.leave))
    for line in made.lines:
        if line.from_ord in fresh and line.to_ord in fresh:
            await store.tie_cards(
                from_name=fresh[line.from_ord],
                to_name=fresh[line.to_ord],
                kind=line.kind,
                says=line.says,
            )
    started = await store.start_run(
        cards=list(fresh.values()),
        repo_key=run.repo_key,
        cwd=run.cwd,
        inside_run=run.id,
        inside_step=card.name,
    )
    await store.set_run_step(
        run_id=run.id, name=card.name, state="going", detail=f"running “{name}”"
    )
    log.info("engine.nested", run=run.id, step=card.name, inside=started.id, process=name)
    return 1


async def _settle_a_process(store: Store, run: Run, card: process.Card, inner: Run) -> int:
    """The outer step of a nested run: has the run inside it finished, and how?

    A nested run that stopped stops the step, and the step stops the outer run — for the reason an
    ordinary failed step does, and it is the same sentence: the steps after it were described on
    the assumption that it worked.
    """
    if inner.finished_at is None and not inner.stopped_why:
        return 0
    if inner.stopped_why:
        why = f"the process inside it stopped: {inner.stopped_why}"
        await store.set_run_step(run_id=run.id, name=card.name, state="failed", detail=why)
        await store.end_run(run.id, why=f"{card.label or card.name}: {why}")
        return 1
    steps = await store.run_steps(inner.id)
    done = sum(1 for one in steps if one.state == "done")
    made = f"ran {done} step{'' if done == 1 else 's'} inside it"
    await store.card_made(card.name, made)
    await store.set_run_step(run_id=run.id, name=card.name, state="done", made=made)
    log.info("engine.nested_done", run=run.id, step=card.name, inside=inner.id)
    return 1


async def _settle(store: Store, run: Run, card: process.Card, step: RunStep) -> int:
    """A step whose task is in flight: has it finished, and what did it produce?"""
    # A step that is a whole process waits on a run rather than on a task, and has no task at all.
    if step.task_id is None:
        inner = await store.run_inside(run.id, card.name)
        if inner is not None:
            return await _settle_a_process(store, run, card, inner)
    task = next((one for one in await store.tasks(limit=500) if one.id == step.task_id), None)
    if task is None:
        await store.set_run_step(
            run_id=run.id, name=card.name, state="failed", detail="its task is gone"
        )
        await store.end_run(run.id, why=f"{card.label or card.name}: its task is gone")
        return 1
    if task.failed_at:
        why = task.detail or "it failed and said nothing"
        await store.set_run_step(run_id=run.id, name=card.name, state="failed", detail=why)
        # The run stops here rather than skipping ahead: the steps after this one were described
        # on the assumption that it worked.
        await store.end_run(run.id, why=f"{card.label or card.name}: {why}")
        log.warning("engine.step_failed", run=run.id, step=card.name, why=why)
        return 1
    if task.finished_at is None:
        return 0

    # It finished. Offer the branch to the gate if this step was allowed to.
    given = allowed.leave_for((await store.card_leaves()).get(card.name))
    made = task.detail or "it finished"
    if "land" in given and task.landed is None:
        offered = await asyncio.to_thread(
            land.land, task.cwd, autostart.worktree_of(task), push="push" in given
        )
        await store.task_landed(task.id, offered.detail, landed=offered.landed)
        made = offered.detail
        if not offered.landed:
            await store.set_run_step(
                run_id=run.id, name=card.name, state="failed", detail=offered.detail
            )
            await store.end_run(run.id, why=f"{card.label or card.name}: {offered.detail}")
            return 1
    await store.card_made(card.name, made[:MOST_MADE])
    await store.set_run_step(run_id=run.id, name=card.name, state="done", made=made[:MOST_MADE])
    log.info("engine.step_done", run=run.id, step=card.name)
    return 1


async def _what_is_known(store: Store, run: Run) -> list[str]:
    """What this console has read that bears on a decision in this project.

    Only things it already computes, and only about this project — a decision about a release does
    not need to hear that another repository is stuck. Each line is a reading of the store, so the
    prompt can honestly call them facts.

    Bounded, because a decision drowned in context is a decision made on the first line of it.
    """
    said: list[str] = []
    # Not filtered on `started_at` first. A task that failed has its `started_at` cleared — it goes
    # back to the queue to be picked up again (`task_failed`) — so an eager filter dropped every
    # failure as well as everything waiting, and this returned nothing at all. Found by coverage:
    # the lines were never reached, and the test that "passed" asserted a count was under a cap,
    # which zero also satisfies.
    tasks = await store.tasks(repo_key=run.repo_key)
    failed = [one for one in tasks if one.failed_at]
    going = [one for one in tasks if one.started_at and not one.finished_at and not one.failed_at]
    if going:
        said.append(f"- {len(going)} piece(s) of work in this project are running right now")
    for one in failed[:THINGS_KNOWN]:
        said.append(f"- work that failed here: {one.instruction.splitlines()[0][:80]}")
    for stuck in (await blockers.blockers(store))[:THINGS_KNOWN]:
        if stuck.repo_key in ("", run.repo_key):
            said.append(f"- stopped: {stuck.what} — {stuck.why}"[:200])
    return said


# How much the console tells a decision about the world. A decision drowned in context is a
# decision made on the first line of it, and the point of these is that each one can settle the
# question on its own.
THINGS_KNOWN = 5


async def _decide(
    store: Store,
    run: Run,
    card: process.Card,
    cards: list[process.Card],
    lines: list[process.Line],
) -> int:
    """A Decision: asked, never given an agent, and it answers with which way out to take."""
    ways = [one for one in lines if one.from_name == card.name and one.kind == "if"]
    if not ways:
        # A decision with nothing to decide between. Not a failure — somebody is still drawing —
        # but the run cannot go on past it.
        await store.set_run_step(
            run_id=run.id, name=card.name, state="held", detail="no ways out are drawn from it yet"
        )
        return 1
    reply, gone = await _ask(
        branch_prompt(
            card,
            ways,
            memory=process.memory_for(card.name, cards, lines),
            known=await _what_is_known(store, run),
        )
    )
    if gone:
        await store.set_run_step(run_id=run.id, name=card.name, state="failed", detail=gone)
        await store.end_run(run.id, why=f"{card.label or card.name}: {gone}")
        return 1
    picked = read_branch(reply, len(ways))
    if not picked:
        # It did not decide. Held rather than a branch taken at random, which is the failure this
        # refuses: a process going the first way out because the model said something
        # conversational.
        await store.set_run_step(
            run_id=run.id,
            name=card.name,
            state="held",
            detail="it did not come back with one of the ways out",
        )
        return 1
    took = ways[picked - 1]
    why = read_why(reply)
    made = f"went {took.says or 'the unlabelled way'}"
    if why:
        made = f"{made} — {why}"
    await store.card_made(card.name, made)
    await store.set_run_step(run_id=run.id, name=card.name, state="done", made=made)
    log.info("engine.decided", run=run.id, step=card.name, went=took.to_name, why=why)
    return 1


async def _wait_for(store: Store, run: Run, card: process.Card, step: RunStep | None) -> int:
    """An Event: the one step that is not work. It waits until somebody says it happened.

    Held, not failed, and the difference is kept: a run waiting on Tuesday's release is a run that
    is fine, and a console that showed it in red would have somebody looking for a fault.
    """
    if step is not None and step.state == "held":
        return 0
    awaits = (card.said.get("awaits") or "").strip()
    await store.set_run_step(
        run_id=run.id,
        name=card.name,
        state="held",
        detail=awaits or "waiting for something to happen",
    )
    log.info("engine.waiting", run=run.id, step=card.name)
    return 1


async def it_happened(store: Store, run_id: str, name: str) -> None:
    """Somebody says the thing an Event was waiting for has happened.

    A human act, and it has to be: whether the release went out is not a thing this console can
    read, and a guess about it would start the rest of a process on the strength of nothing
    (CLAUDE.md, rule five).
    """
    await store.set_run_step(run_id=run_id, name=name, state="done", made="it happened")
    await store.card_made(name, "it happened")


async def run(store: Store) -> None:
    """The loop, for the life of the console.

    Same shape as the other four and the same reasons: a bad tick logs and waits, and a cancel
    goes through rather than being swallowed — `app.lifespan` cancels this and then waits for it,
    and a tick sits in a thread for as long as a landing takes.
    """
    while True:
        try:
            await tick(store)
        except Exception:
            log.exception("engine.tick_failed")
        await asyncio.sleep(TICK_SECONDS)
