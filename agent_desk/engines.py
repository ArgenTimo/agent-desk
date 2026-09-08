"""Which answer engines this console actually has.

"Развилка на 2 карточки: Claude Opus и GPT 4.1… Здесь же честная граница: сегодня консоль умеет
звать один движок ответов (плюс локальный, если настроен). Вторая модель — это либо второй
настроенный движок, либо ничего; карточка не должна делать вид, что умеет звать то, чего нет."

The idea wrote its own boundary and this module is that sentence in code. There are one or two
engines, they are the ones `config.py` names, and a card that offered a third would be a control
that fails when pressed — which is the failure `allowed.py` was written to prevent, in a different
costume.

## What a model card cannot say

Temperature, a token limit, a system prompt. Not because they are bad ideas: because
`claude -p --output-format stream-json` takes none of them, so a field for one would be a box
somebody fills in and nothing reads. When the engine grows a flag, the field can. Until then the
card says which engine, and that is the whole of what this console can honour.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_desk.config import settings


@dataclass(frozen=True)
class Engine:
    """One thing that can be asked a question."""

    name: str
    says: str
    # The binary to run, or "" for the primary — which is what `session.stream_answer` means by an
    # empty string, and repeating that convention beats translating it.
    binary: str


def available() -> tuple[Engine, ...]:
    """The engines configured on this machine, in the order they would be tried.

    The primary is always here: it is what every block is answered with and the console says so
    plainly when it is not installed. The second is here only when somebody set it, which is not
    every install and is never a default — "a local model is a thing you have to have running".
    """
    found = [Engine(name="claude", says=f"the answer engine ({settings.claude_bin})", binary="")]
    if settings.local_model_bin:
        found.append(
            Engine(
                name="local",
                says=f"a model on this machine ({settings.local_model_bin})",
                binary=settings.local_model_bin,
            )
        )
    return tuple(found)


def named(what: str) -> Engine | None:
    """The engine a card asked for, or `None` when this console does not have it.

    `None` is the answer that matters. A card naming an engine nobody configured must stop the step
    and say so, not quietly fall through to the default — a harness whose two branches ran on the
    same model would produce a comparison of a thing with itself and no sign that it had.
    """
    wanted = what.strip().lower()
    return next((one for one in available() if one.name == wanted), None)


def is_an_engine(what: str) -> bool:
    return named(what) is not None
