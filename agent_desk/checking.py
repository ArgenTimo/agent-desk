"""What an answer has to be, in a form a machine can decide.

"Без этого верстак — площадка для игры. С этим — харнесс: карточка-проверка на выходе шага
(содержит, не содержит, разбирается как JSON, короче N) и понятное «прошло/не прошло» на схеме.
Проверка — это Result с зубами: то, что уже описано полем «что считается сделанным», но
проверяемое машиной."

A Result already says what counts as done. It says it to a person, in a sentence, and nothing reads
it. This is the same field read by something that can decide — and only when it is written in one
of four forms, because a check that guessed at prose would be the thing this file exists to stop: a
pass or a fail invented from a sentence somebody wrote for a human.

## Four, and why not a fifth by regular expression

`contains`, `does not contain`, `is json`, `shorter than N` are what somebody actually asserts about
an answer, and each is unambiguous to read and to explain. A regular expression would cover all of
them and be unreadable on the card, which is the same argument the five line kinds are held to: a
vocabulary is worth having when every word in it can be read off the diagram.

## A sentence that is not one of the four is not a failure

It is a Result as Results have always been: a description for a person. Nothing checks it, the card
says nothing about passing, and the run is unaffected. Turning "the migration is applied cleanly"
into a failed check would make every drawing that predates this one red.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# Written the way somebody says it, in either language this console is used in. The forms are
# matched whole: "contains a thing, unless it is empty" is a sentence, not a check, and reading the
# first three words of it would make a check out of a caveat.
_CONTAINS = re.compile(r"\A(?:contains|содержит)\s+(.+)\Z", re.IGNORECASE | re.DOTALL)
_MISSING = re.compile(
    r"\A(?:does not contain|doesn't contain|не содержит)\s+(.+)\Z", re.IGNORECASE | re.DOTALL
)
_JSON = re.compile(
    r"\A(?:is\s+json|parses\s+as\s+json|это\s+json|разбирается\s+как\s+json)\Z", re.I
)
_SHORTER = re.compile(
    r"\A(?:shorter than|короче)\s+(\d{1,7})(?:\s*(?:characters|chars|символов|знаков))?\Z",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Check:
    """One thing an answer has to be."""

    kind: str
    # What it is compared against: the text for `contains`, the number for `shorter`, "" for json.
    against: str = ""

    @property
    def says(self) -> str:
        """The check in the words the card shows, so what was checked is readable next to whether
        it passed."""
        return {
            "contains": f"contains {self.against}",
            "missing": f"does not contain {self.against}",
            "json": "is JSON",
            "shorter": f"shorter than {self.against} characters",
        }[self.kind]


def read(said: str) -> Check | None:
    """The check this Result asks for, or `None` when it is a sentence for a person."""
    one = said.strip().strip(".").strip()
    if not one:
        return None
    if _JSON.match(one):
        return Check(kind="json")
    found = _SHORTER.match(one)
    if found:
        return Check(kind="shorter", against=found.group(1))
    found = _MISSING.match(one)
    if found:
        return Check(kind="missing", against=found.group(1).strip().strip("\"'“”«»"))
    found = _CONTAINS.match(one)
    if found:
        return Check(kind="contains", against=found.group(1).strip().strip("\"'“”«»"))
    return None


def passes(check: Check, answer: str) -> tuple[bool, str]:
    """Whether the answer satisfies it, and what to say either way.

    The sentence matters as much as the verdict. "It failed" is a fact somebody has to go and
    investigate; "it does not contain 'ERROR', and the answer is 4kb of prose" is one they can act
    on — so a failure says what was asked and what was there instead.
    """
    if check.kind == "json":
        try:
            json.loads(answer)
        except ValueError as why:
            return False, f"it is not JSON: {why}"
        return True, "it is JSON"
    if check.kind == "shorter":
        limit = int(check.against)
        if len(answer) >= limit:
            return False, f"it is {len(answer)} characters, and had to be shorter than {limit}"
        return True, f"it is {len(answer)} characters, under {limit}"
    if check.kind == "missing":
        if check.against.lower() in answer.lower():
            return False, f"it contains “{check.against}”, and had to not"
        return True, f"it does not contain “{check.against}”"
    if check.against.lower() not in answer.lower():
        return False, f"it does not contain “{check.against}”"
    return True, f"it contains “{check.against}”"
