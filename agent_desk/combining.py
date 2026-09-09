"""What a combine asks, and what it means to change it.

*«В алхимии вода + огонь = пар. В работе две карточки + вопрос = новый документ. Правило — это то,
что превращает пару в третье, и оно должно быть видимым и сменяемым: одна и та же пара в разных
правилах даёт разное.»*

The gesture is `060-what-two-cards-made.sql`; this is the sentence it sends. Pure and separate
because the default is a piece of product wording that two places need to agree on — the route that
sends a combine and the panel that shows somebody what it will ask — and a default written twice is
a default that drifts.
"""

from __future__ import annotations

# Long enough to be a rule and short enough to read on a tooltip. A person replacing it is the
# point, so this is a starting position rather than a careful piece of prompt engineering: it asks
# for the one thing a combine is for, which is what neither card says on its own.
DEFAULT = (
    "Make one thing out of these two. Say what having them together gives that neither gives "
    "alone, and say it in a few sentences. Do not summarise the two cards back to me."
)

# What a rule may be. Past this it is not a rule any more, it is the work — and a prompt somebody
# pasted a document into is a prompt that costs the same on every combine after it.
MOST_CHARS = 600


def rule(said: str) -> str:
    """The rule to send, given what a bench has been told. Empty means the default.

    Trimmed rather than refused: somebody who pasted too much gets a rule that is too long by the
    end and still works, which beats a gesture that stops working until they go and edit it.
    """
    trimmed = said.strip()[:MOST_CHARS].strip()
    return trimmed or DEFAULT
