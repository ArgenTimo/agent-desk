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
# The fifth form, and the only one whose answer is not on the card. «Проверка вида "равно
# ожидаемому" — седьмая форма в checking.py, где ожидаемое берётся из входа.» What a run is
# measured against changes with every row of the set, so it travels with the input rather than with
# the check — which is exactly what makes one check card into a measurement over five hundred rows
# instead of five hundred cards.
_EXPECTED = re.compile(
    r"\A(?:is\s+the\s+expected(?:\s+answer)?|равно\s+ожидаемому)\Z", re.IGNORECASE
)


@dataclass(frozen=True)
class Check:
    """One thing an answer has to be."""

    kind: str
    # What it is compared against: the text for `contains`, the number for `shorter`, "" for json
    # and for `expected` — where what to compare with arrives with the input instead.
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
            "expected": "is the expected answer",
        }[self.kind]


def read(said: str) -> Check | None:
    """The check this Result asks for, or `None` when it is a sentence for a person."""
    one = said.strip().strip(".").strip()
    if not one:
        return None
    if _JSON.match(one):
        return Check(kind="json")
    if _EXPECTED.match(one):
        return Check(kind="expected")
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


def passes(check: Check, answer: str, expected: str = "") -> tuple[bool, str]:
    """Whether the answer satisfies it, and what to say either way.

    The sentence matters as much as the verdict. "It failed" is a fact somebody has to go and
    investigate; "it does not contain 'ERROR', and the answer is 4kb of prose" is one they can act
    on — so a failure says what was asked and what was there instead.

    `expected` is what this row of a set says the answer should have been, and only the `expected`
    form reads it. A check whose answer is written on the card cannot measure a prompt over five
    hundred rows; one whose answer comes with the row can.
    """
    if check.kind == "expected":
        # Compared as words rather than as characters: a reader that answers "idea." and one that
        # answers "idea" have not disagreed about anything.
        got = answer.strip().strip(".").strip().lower()
        want = expected.strip().strip(".").strip().lower()
        if not want:
            return False, "nothing said what the answer should have been"
        if got != want:
            return False, f"it said “{answer.strip()[:80]}”, and the answer was “{expected}”"
        return True, f"it said “{expected}”"
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


# --- and the other half: a check nothing mechanical can decide ------------------------------------
# "Временный блок-проверка, в первой итерации берёт вводный вопрос/карточку + то что мы получили от
# сервиса и возвращает одно из двух."
#
# The four forms above are what a machine can decide on its own, and they cost nothing. Most of what
# somebody actually wants checked is not one of them — "does this answer the question that was
# asked" is a judgement, and the only thing here that can make one is the answer engine.
#
# So a check card reads its own sentence first. If it is one of the four, it is decided for free and
# instantly; if it is not, it is asked. The card says which happened, because "it passed" from a
# regular expression and "it passed" from a model are not the same claim and a person acting on
# either deserves to know which they have.
_VERDICT = re.compile(r"\A\s*(yes|no|да|нет)\b[\s.:,—-]*(.*)\Z", re.IGNORECASE | re.DOTALL)

# What a judgement may say back. Long enough for a reason, short enough that a card holding it is
# still a card.
WHY_CHARS = 400


def judgement_prompt(asked: str, got: str, said: str) -> str:
    """Ask whether an answer meets a condition written in prose.

    One word first and the reason after it, which is the shape every other short call in this
    repository uses: a verdict buried in a paragraph is a verdict something has to parse out of
    prose, and parsing prose is how a check starts inventing its own answers.

    The condition goes last. It is the thing being decided, and a model that has read the question
    and the answer before it reads what to look for is one that judges rather than pattern-matches.
    """
    return (
        "Here is a question somebody asked, the answer they got, and what that answer had to be.\n"
        "Say whether the answer meets the condition.\n\n"
        "Reply with one word — yes or no — and then, on the same line, one sentence saying why.\n"
        "Say no if you cannot tell: a check that guesses is worse than one that admits it.\n\n"
        f"## What was asked\n{asked.strip()}\n\n"
        f"## What came back\n{got.strip()}\n\n"
        f"## What it had to be\n{said.strip()}\n"
    )


def read_verdict(reply: str) -> tuple[bool, str] | None:
    """The verdict and its sentence, or `None` when the reply was not one.

    `None` rather than a fail: a model that answered something else has not decided anything, and
    recording that as "it did not pass" would be a failure invented from silence — the fifth rule,
    in the one place where inventing one is easiest.
    """
    found = _VERDICT.match(reply.strip())
    if found is None:
        return None
    yes = found.group(1).lower() in ("yes", "да")
    why = " ".join(found.group(2).split())[:WHY_CHARS]
    return yes, why or ("it does" if yes else "it does not")
