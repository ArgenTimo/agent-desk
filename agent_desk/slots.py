"""A prompt with places in it for what came in along the lines.

"Промпт — это шаблон, а не текст: в нём места, куда подставляется то, что пришло по связям. Без
слотов схема из пяти карточек — это пять отдельных промптов, которые надо править по одному."

And the other half of the same feature: *"Карточка ввод (текстовое поле ввода, я могу просто писать
в неё что угодно)… Именованное значение, которое подставляется дальше по цепочке. Это то, что
делает схему переиспользуемой: поменял ввод — прогнал ту же схему заново."*

Neither is anything on its own. A value nothing substitutes is a note; a slot with nothing to fill
it is a prompt with a brace in it. So they are one module and one commit: a card's label is the
name of what it holds, and `{that name}` in a prompt downstream is where it goes.

## Why the label and not an id

Because somebody types the prompt. `{the article}` is a thing a person writes; `{step:01M1XA…}` is
a thing they paste, wrongly, once. The cost is that two cards with the same label are ambiguous —
which is why that case is named rather than resolved: the first one wins and the reader is told
there were two, because silently picking one is how a pipeline produces the wrong answer for a
week.

## What an unfilled slot does

Stays. A prompt that quietly lost `{the article}` is a prompt that ran against nothing and answered
confidently; one that still says `{the article}` is one whose answer is visibly about the wrong
thing. Nothing here fails the run — a half-drawn pipeline is the normal state of one being built —
and `left` names every slot that found nothing, so a caller can say so.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# `{a name}` — letters, digits, spaces, dashes and underscores, and nothing else. Deliberately not
# `.+`: a prompt about JSON is full of braces, and a pattern that matched `{"key": 1}` would eat
# the example somebody was asking about.
_SLOT = re.compile(r"\{([A-Za-z0-9 _\-—]{1,60})\}")


@dataclass(frozen=True)
class Filled:
    said: str
    # The names that found nothing, in the order they appear. Empty is the ordinary case.
    left: tuple[str, ...] = ()
    # Names that matched more than one card. Named rather than resolved.
    twice: tuple[str, ...] = ()


def names_in(said: str) -> tuple[str, ...]:
    """Every slot in this prompt, in order, without repeats."""
    seen: list[str] = []
    for found in _SLOT.finditer(said):
        name = found.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def values_from(cards: Sequence[object]) -> dict[str, list[str]]:
    """What each incoming card offers, by the name on it.

    What a card offers is what it *produced* where it has run, and what it *says* where it has not
    — an input card has no work to do and its value is what somebody typed into it. Both are the
    same thing to the prompt downstream, which is why an input card needs no kind of its own.
    """
    found: dict[str, list[str]] = {}
    for card in cards:
        label = str(getattr(card, "label", "") or "").strip()
        if not label:
            continue
        made = str(getattr(card, "made", "") or "").strip()
        said = getattr(card, "said", {}) or {}
        value = made or str(said.get("what", "") or said.get("asks", "") or "").strip()
        if value:
            found.setdefault(label, []).append(value)
    return found


def fill(said: str, values: Mapping[str, Sequence[str]]) -> Filled:
    """The prompt with its slots filled from the cards that lead into it."""
    left: list[str] = []
    twice: list[str] = []

    def one(found: re.Match[str]) -> str:
        name = found.group(1).strip()
        offered = list(values.get(name, ()))
        if not offered:
            left.append(name)
            return found.group(0)
        if len(offered) > 1 and name not in twice:
            twice.append(name)
        return offered[0]

    return Filled(said=_SLOT.sub(one, said), left=tuple(left), twice=tuple(twice))
