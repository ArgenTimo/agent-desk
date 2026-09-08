"""Two runs of one drawing, side by side.

"Тестировать пайплайн — значит запускать его несколько раз и смотреть, что изменилось."

The history was already there and nothing showed it. Every run keeps what each of its steps
produced (`run_step.made`), which is exactly what 036 deliberately does *not* keep on the card —
the card holds the last result, and the runs hold all of them. So this needs no storage at all: it
needs the comparison, and a place to read it.

## What "changed" means here, and what it does not

A step that produced different words is marked changed. That is a fact about two strings and this
module claims nothing beyond it: it does not say the pipeline got better, and it does not say the
difference is caused by the edit somebody made in between. A model asked the same question twice
answers differently, and a comparison that hid that would be worse than none — it would make
noise look like progress.

So the honest thing to show is what each run produced, and where they differ, and let the person
reading it decide what that means. A verdict here would be a guess wearing a checkmark.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

# How much of a step's output is shown on a row. Enough to see that two answers differ and roughly
# how; the whole of either is one click away on the step itself.
SAID_CHARS = 400


@dataclass(frozen=True)
class Row:
    """One step, in both runs."""

    name: str
    label: str
    before: str
    after: str

    @property
    def changed(self) -> bool:
        return self.before.strip() != self.after.strip()

    @property
    def marks(self) -> list[tuple[str, str]]:
        """The two, word by word, with what changed marked."""
        return differences(self.before, self.after)

    @property
    def says(self) -> str:
        """What happened to this step between the two, in the words the panel uses."""
        if not self.before and not self.after:
            return "neither run got here"
        if not self.before:
            return "only the second run got here"
        if not self.after:
            return "only the first run got here"
        return "different" if self.changed else "the same"


# Words, and the spaces between them kept as their own pieces. Splitting on whitespace and
# rejoining with a single space would rewrite the indentation of a code block into one line and
# call the result a difference.
_WORDS = re.compile(r"\s+|\S+")


def differences(before: str, after: str) -> list[tuple[str, str]]:
    """The two texts as one sequence of pieces, each marked with where it belongs.

    "Два ответа, показанные друг под другом с отличиями." Two answers side by side are readable;
    two answers side by side with the changed words marked are *comparable*, which is the thing the
    whole harness is assembled to reach.

    Word by word rather than line by line. Two answers to one prompt are usually the same shape
    with different words in it, and a line diff of those marks every line as changed — which says
    "it is all different" about two texts that differ in three words.

    Three marks: `same`, `before`, `after`. A caller renders the first in both columns and the
    other two in one each; nothing here decides how it looks.
    """
    first, second = _WORDS.findall(before), _WORDS.findall(after)
    found: list[tuple[str, str]] = []
    for what, i, j, k, m in difflib.SequenceMatcher(None, first, second).get_opcodes():
        if what in ("replace", "delete"):
            found.append(("before", "".join(first[i:j])))
        if what in ("replace", "insert"):
            found.append(("after", "".join(second[k:m])))
        if what == "equal":
            found.append(("same", "".join(first[i:j])))
    return [(mark, text) for mark, text in found if text]


def _said(steps: Iterable[object]) -> dict[str, str]:
    return {
        str(getattr(step, "name", "")): str(getattr(step, "made", "") or "")[:SAID_CHARS]
        for step in steps
    }


def against(
    earlier: Sequence[object], later: Sequence[object], labels: Mapping[str, str] | None = None
) -> list[Row]:
    """What the two runs produced, step by step, in the order the later one ran them.

    The later run's order, because that is the drawing as it is now — a step somebody added since
    belongs where they put it, and a step they removed belongs at the end rather than in the middle
    of a shape it is no longer part of.
    """
    before, after = _said(earlier), _said(later)
    names = list(after) + [name for name in before if name not in after]
    said = labels or {}
    return [
        Row(
            name=name,
            label=said.get(name, name),
            before=before.get(name, ""),
            after=after.get(name, ""),
        )
        for name in names
    ]


def in_a_word(rows: Sequence[Row]) -> str:
    """The one line above the table. Counted rather than judged: "three of five steps differ" is a
    fact, and "it got better" is not one this program could know."""
    if not rows:
        return "neither run produced anything"
    changed = sum(1 for row in rows if row.changed)
    if not changed:
        return f"all {len(rows)} steps produced the same thing"
    return f"{changed} of {len(rows)} steps produced something different"
