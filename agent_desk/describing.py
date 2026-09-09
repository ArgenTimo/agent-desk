"""What a finished run knows, written out as the description of a change.

*«Прогон знает: что просили, какие шаги прошли, что каждый сделал, какие развилки выбраны и почему,
что легло в ветку. Это и есть описание изменения — лучше, чем напишет человек по памяти через день.
Кнопка «сделать описание PR» на завершённом прогоне. Дёшево, и попадает ровно в тот момент, когда
писать описание больше всего не хочется.»*

## Facts first, prose after

The prompt is a list of what happened and an instruction to turn it into a description. It is not a
summary of a summary: every line under "what happened" is a row — the step's label, its state, what
it produced, and for a Decision the way it went and why. The model's job is the wording, not the
content, which is the difference between a description somebody can check and one they have to
believe.

Steps that did not run are named too. "Эти три не выполнялись" belongs in a description of a change
far more than it belongs nowhere, and a reader who finds out later that half the drawing was skipped
stops trusting the other half.

## Nothing is offered about the code

This console does not read the diff. It knows what was asked and what each step reported, and the
prompt says so plainly — a description that claimed to summarise the changes would be summarising a
thing it never saw, which is the fifth rule with a heading on it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# How much of what one step produced travels. Long enough for the sentence a step reports itself
# with, short enough that a run of ten does not become a transcript.
MADE_CHARS = 400


@dataclass(frozen=True)
class Step:
    """One step of a finished run, as the description needs it."""

    label: str
    state: str
    made: str = ""
    detail: str = ""


def _short(said: str) -> str:
    words = " ".join(said.split())
    return words if len(words) <= MADE_CHARS else words[: MADE_CHARS - 1] + "…"


def what_to_write(asked: str, steps: Sequence[Step]) -> str:
    """The prompt that turns a run into a description of the change.

    `asked` is what the run was given to do, where it was given anything. A run started from a
    drawing alone has none, and the prompt says that rather than inventing a request nobody made.
    """
    lines = [
        "Write the description of a change, from what a run of it actually did.",
        "",
        "Two paragraphs at most, then a short list of what was done. No preamble, no heading, no",
        "closing line — this goes straight into a pull request.",
        "",
        "Use only what is below. You have not seen the code and must not describe it: say what the",
        "steps reported, not what you suppose the diff contains.",
        "",
    ]
    if asked.strip():
        lines += ["## What was asked", asked.strip(), ""]
    else:
        lines += [
            "## What was asked",
            "Nothing was written down — the run was started from the drawing itself.",
            "",
        ]
    lines.append("## What happened")
    done = [one for one in steps if one.state == "done"]
    for one in done:
        said = f"- {one.label}: {_short(one.made) or 'it reported nothing'}"
        lines.append(said)
    if not done:
        lines.append("- nothing finished")
    skipped = [one for one in steps if one.state != "done"]
    if skipped:
        lines += ["", "## What did not run"]
        # Named rather than left out: a reader who finds out later that half the drawing was
        # skipped stops trusting the other half.
        lines += [
            f"- {one.label}: {one.state}{f' — {_short(one.detail)}' if one.detail else ''}"
            for one in skipped
        ]
    return "\n".join(lines)
