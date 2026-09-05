"""Is this thought one that is already written down? (docs/05-ideas.md)

A notebook that grows a second row every time somebody says the same thing twice stops being a
notebook. The owner asked for this three separate times and in the same words each time: before
adding an idea, check the ones already there — a new row only when nothing matches, otherwise
attach it under the idea it belongs to, or update the one it repeats.

Three rules shape what this module is allowed to do, and all three come from the same place.

**Capture never waits for it.** The thought is written down first, always, by
`inbox.capture`. This runs afterwards and can fail freely: an unavailable model leaves a list with
one honest duplicate in it, which is a far smaller failure than a capture that lost the idea.

**It moves rows, and it never touches a word anybody wrote.** A judgement that two things are the
same is a judgement, and this one is a model's. There is no statement in this program that writes
`idea.text` and this module does not add one (docs/05-ideas.md) — so a repeat is *hung under* the
idea it repeats rather than folded into it. Both wordings stay readable, the list stops showing
two rows that look like two decisions, and if the judgement was wrong the thought is still there
to be dragged back out. Nothing a person has touched is moved at all.

**It never groups two things that are merely near each other.** The failure this replaces is a
list of near-duplicates; the failure it could introduce is worse — two different thoughts filed as
one, and the second one gone from the list somebody reads. So the prompt is strict, the default is
`new`, and anything unparsable is `new`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from agent_desk.answer.session import AnswerFailed, stream_answer
from agent_desk.store.repo import Idea, Store

# How many existing ideas one judgement is shown. A pool larger than this is a pool where the
# model's attention is the bottleneck rather than its judgement, and the newest are the ones a
# repeat is most likely to repeat.
MOST_COMPARED = 40

_VERDICT = re.compile(r"\A(new|same|under)(?:\s+(\d+))?\Z", re.IGNORECASE)


def kin_prompt(text: str, ideas: Sequence[str]) -> str:
    """Ask one question with three answers, and make the safe one the easiest to give."""
    lines = [
        "A developer just wrote a new idea in their notebook. Below are the ideas already in it.",
        "",
        "Answer with exactly one of these, and nothing else:",
        "",
        "- `new` — the new idea is not in the list.",
        "- `same N` — the new idea is the same idea as N, said again or said better.",
        "- `under N` — the new idea is a *part* of N: doing N would include doing this.",
        "",
        "Be strict, and prefer `new` whenever you are not sure. Two ideas about the same feature",
        "are not the same idea, and two ideas that would be done at the same time are not the",
        "same idea either. Getting this wrong hides somebody's thought inside somebody else's,",
        "and they will never see it again.",
        "",
        "## Already written down",
    ]
    lines += [f"{index}. {idea}" for index, idea in enumerate(ideas, start=1)]
    lines += ["", "## The new idea", text]
    return "\n".join(lines)


def read_kin(reply: str, count: int) -> tuple[str, int]:
    """`("new", 0)`, `("same", n)` or `("under", n)`. Anything unusable is `new`."""
    answer = reply.strip().rstrip(".").splitlines()
    first = answer[0].strip() if answer else ""
    found = _VERDICT.match(first)
    if found is None:
        return "new", 0
    verdict = found.group(1).lower()
    if verdict == "new":
        return "new", 0
    number = int(found.group(2)) if found.group(2) else 0
    if not 1 <= number <= count:
        return "new", 0
    return verdict, number


async def judge(text: str, ideas: Sequence[str]) -> tuple[str, int]:
    """Never raises: an unavailable model means this is a new idea, which is what it looked like."""
    if not ideas:
        return "new", 0
    try:
        reply = "".join([chunk async for chunk in stream_answer(kin_prompt(text, ideas))])
    except (AnswerFailed, OSError):
        return "new", 0
    return read_kin(reply, len(ideas))


def _untouched(idea: Idea) -> bool:
    """Has anybody done anything to this row since it was written?

    A state somebody set, or a summary somebody wrote, is a person saying what this card is. This
    module does not argue with that, which is the same rule the splitter and the summariser follow.
    """
    return idea.state == "new"


async def place(store: Store, idea: Idea) -> str:
    """Put one freshly captured idea where it belongs. Returns what was done, for the log.

    The three answers, and the first is the ordinary one:

    - `new` — nothing happens, which is the whole of the default;
    - `under N` — it becomes a sub-idea of N;
    - `same N` — the same, and the word is kept apart only so the log says which was meant.

    Two answers and one action is deliberate. The action that `same` seems to want — fold the
    wording into the idea it repeats — would be this program writing `idea.text`, which nothing in
    it does. Hanging the repeat underneath loses nothing, reads the same in a list, and can be
    undone by dragging.
    """
    # Re-read rather than trust the row this was handed: a summariser ran between the capture and
    # this, and a person reading the list can touch a card in that gap. The same race the
    # summariser guards against, guarded the same way.
    current = await store.idea(idea.id)
    if current is None:
        return "left alone: it is not there any more"
    if not _untouched(current):
        return "left alone: somebody has already touched it"
    idea = current

    pool = [
        other
        for other in await store.ideas(state="new")
        if other.id != idea.id and other.parent_id != idea.id and other.id != idea.parent_id
    ][:MOST_COMPARED]
    if not pool:
        return "new: nothing to compare it with"

    verdict, number = await judge(idea.text, [one.summary or one.text for one in pool])
    if verdict == "new":
        return "new"

    match = pool[number - 1]
    if not await store.set_idea_parent(idea.id, match.id):
        return "new: it would have made a loop"
    return verdict
