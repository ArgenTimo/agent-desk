"""What somebody is asking to be put in front of them, when they ask for a thing rather than a word.

"И способ попросить: «покажи тикеты из спринта», «покажи открытые PR-ы»."

Everything that reaches the workbench today got there by being dragged, or by an answer that drew
it. A request to *show what already exists somewhere* is neither: nothing is composed and nothing
is decided — a list is read from a place that has it, and each row becomes a card.

## Read here rather than asked of a model

The same argument `agent_desk/ideas/waking.py` is served under. This is a regular expression over
a handful of words in two languages, it cannot fail on a busy machine or a spent budget, and what
it decides is which of two lists to fetch — a decision with an answer, not a judgement. A model
call would add a second way for "покажи PR-ы" to do nothing.

## Two, and the closed list is the point

`tickets` and `pulls` are what this console can read (docs/adr/0010): a project's own board and its
open pull requests. Anything else it is asked for, it cannot fetch, and the honest answer is to say
so rather than to answer with the nearest thing it does have.
"""

from __future__ import annotations

import re

# What can be asked for, and what each is called when the console says it back.
WHAT: dict[str, str] = {
    "tickets": "the tickets on this project's board",
    "pulls": "the open pull requests",
}

# `pr` on its own, because that is what people type, and `пр` is not included for the opposite
# reason: it is a preposition fragment in Russian and would match half the sentences in the pool.
_PULLS = re.compile(
    r"\b(pull\s*requests?|pull-requests?|prs?|пул[\s-]*реквест\w*|пулл?[\s-]*реквест\w*)\b",
    re.IGNORECASE,
)
_TICKETS = re.compile(
    r"\b(tickets?|issues?|тикет\w*|задач\w*|тасок|таски|таск\w*)\b",
    re.IGNORECASE,
)


def what_to_show(text: str) -> str:
    """Which list is being asked for, or "" for a request naming neither.

    Pull requests are looked for first, and it is not arbitrary: "покажи тикеты и PR-ы" names both,
    and a console that fetched the tickets would have answered the easier half of the question
    silently. Fetching the pull requests and saying which one it read is a wrong guess somebody can
    see; fetching the tickets is a wrong guess that looks like the whole answer.
    """
    if _PULLS.search(text):
        return "pulls"
    if _TICKETS.search(text):
        return "tickets"
    return ""


def says(what: str) -> str:
    """What the console calls the thing it fetched, in a sentence."""
    return WHAT.get(what, "")
