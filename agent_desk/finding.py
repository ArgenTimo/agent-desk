"""What a card that goes and finds out comes back with.

*«Карточка-исполнитель, которая сама пойдёт в интернет, разузнает всё что попросили и вернётся с
новыми карточками, основанными на полученных данных.»*

A button already sends a request. What it could not do is bring anything back except one answer
card — and an answer card is a paragraph, which is read whole or not at all. Cards are taken one at
a time, and the half nobody needs stays unread instead of being scrolled past.

## What is claimed here, and what is not

Not that anything browses. Whether the engine behind an answer can reach the internet is the CLI's
business and changes with its configuration, so the card says what it does — it asks, and what comes
back becomes cards — and never that it went anywhere. Naming Google Drive as a connector kind does
not make this program able to read a Drive (`agent_desk/connectors.py`), and the same rule holds
here.

## One finding a line, and the answer says so

The request has a tail added to it saying how to answer. That is the whole of the parsing problem:
a reply asked for in a shape arrives in that shape most of the time, and a reply that does not is
read as no findings rather than as one long one — which is the safe direction, because the answer
itself is still there on its own card.
"""

from __future__ import annotations

import re

# How many findings one press may bring back. A bench is something a person arranges, and twenty
# cards arriving at once is not an arrangement — it is the paragraph again, in card form.
MOST = 12

# How much of one finding travels. It becomes an idea, and an idea's first line is its summary.
MOST_CHARS = 600

HOW_TO_ANSWER = (
    "\n\nAnswer as findings, one per line, each beginning with `- `. A finding is one fact and "
    "the reason it matters, in a sentence somebody could read on a card without opening it. "
    "Say nothing else — no preamble, no numbering, no closing paragraph. If you found nothing, "
    "answer with one line saying so."
)

_FINDING = re.compile(r"\A\s*[-*•]\s+(.+?)\s*\Z")


def what_to_ask(asks: str) -> str:
    """The request, with the shape the answer has to arrive in.

    Added here rather than written into every button, because a person writing a button is writing
    what they want to know — and a shape they have to remember to append is a shape half the
    buttons will be missing.
    """
    return asks.rstrip() + HOW_TO_ANSWER


def read_findings(reply: str) -> list[str]:
    """The findings in a reply, in the order they were given.

    A reply with no lines in the shape is no findings. Not one long finding: the answer is on its
    own card either way, and a bench that grew a card holding somebody's whole reply is the
    paragraph this exists to break up.
    """
    found = []
    for line in reply.splitlines():
        one = _FINDING.match(line)
        if one and one.group(1).strip():
            found.append(one.group(1).strip()[:MOST_CHARS])
    return found[:MOST]
