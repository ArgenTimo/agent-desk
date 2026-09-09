"""Making a tool out of a description of one.

*«Также можно описать суть инструмента, и сервис сам создаст по описанию такой инструмент на
верстаке (сохраняет инструмент либо сам пользователь, либо сервис, если пользователь попросил об
этом).»*

The parenthesis is the design. Making the card is cheap and undoable — one card on a bench, taken
off with one press — so it happens on the asking. *Keeping* it is a decision about a list that
outlives every chat, so it stays the separate act it already is (`065-a-tool-you-keep.sql`).

## Two kinds and no third

A tool is a button or a check, because those are the two card kinds that hold behaviour. Asking the
model to invent a third would produce a word this console cannot make a card from, and the honest
answer to "make me a tool that opens Jira" is that it cannot yet — which the reader gives by
refusing the reply rather than by making a button that says "open Jira" and does nothing of the
sort.

Pure: the prompt and the reading of the reply. What to do with what comes back is the route's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# What a made tool may be. The same two the store accepts, said here because this is what the model
# is told and the two lists disagreeing is how a reply gets accepted and then refused.
KINDS = ("button", "check")

# A name sits in a list beside the projects, so it is a label rather than a sentence.
NAME_CHARS = 40


@dataclass(frozen=True)
class Made:
    """What one description asked for."""

    kind: str
    name: str
    said: str


_LINE = re.compile(r"\A\s*(kind|name|does)\s*:\s*(.+?)\s*\Z", re.IGNORECASE)


def what_to_make(said: str) -> str:
    """Ask for a tool in three lines and nothing else.

    Three named lines rather than JSON: the reply is read by a regular expression here, and a model
    that wraps JSON in a sentence of apology produces something a parser has to guess at. A line
    that starts with a word is one it either has or has not.
    """
    return (
        "Somebody described a tool they want on their workbench. Make it.\n\n"
        "A tool is one of two things and there is no third:\n"
        "  button — it holds a request and sends it when pressed\n"
        "  check  — it holds a condition and says whether an answer meets it\n\n"
        "Answer in exactly three lines and nothing else:\n\n"
        "  kind: button\n"
        "  name: decompose\n"
        "  does: break what is chosen into the parts it is made of\n\n"
        "`does` is what the card will actually hold — the request a button sends, or the condition "
        "a check tests. Write it as the instruction itself, not as a description of it.\n"
        "If what they asked for is neither of those two things, answer with the single word `no`.\n\n"
        f"## What they said\n{said.strip()}\n"
    )


def read_made(reply: str) -> Made | None:
    """The tool the reply asked for, or `None`.

    `None` covers both refusals: the model saying `no` because the thing is neither a button nor a
    check, and a reply this cannot read. They are the same outcome — nothing is made — and telling
    them apart would be inventing a distinction the person cannot act on differently.
    """
    found: dict[str, str] = {}
    for raw in reply.splitlines():
        line = _LINE.match(raw)
        if line is not None:
            found[line.group(1).lower()] = line.group(2)
    kind = found.get("kind", "").lower()
    name = found.get("name", "").strip()[:NAME_CHARS]
    does = found.get("does", "").strip()
    if kind not in KINDS or not name or not does:
        return None
    return Made(kind=kind, name=name, said=does)
