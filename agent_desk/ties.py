"""What a line between two cards means: then, if, when, makes, with.

The second half of the vocabulary `agent_desk/roles.py` began. From the first user's feedback:
*"дальше создаём процесс взаимодействия между"* — and the reason it has to be typed is the same
reason the cards do.

A line that says only "these two are related" is a picture. Read a bench of it and you learn that
somebody thought six things belong together, which you already knew, because they are on the same
bench. A line that says **then**, **if**, **when** is a sentence: it can be read top to bottom by
somebody who was not there, and — later — executed in that order by something that was not
anybody.

## The five, and why not more

- **then** — and after that. The backbone of every process anybody draws.
- **if** — the way out of a Decision, and the only one that carries words of its own: a branch
  without its condition on it is a fork nobody can follow.
- **when** — the way out of an Event. "This happened, so do that."
- **makes** — an Action produces a Result. Separate from `then` because "what came out of it" and
  "what happens next" are different questions, and a diagram that answers them with one arrow
  cannot say that a step produced something *and* continued.
- **with** — plainly related, no order implied. The one that was already here, kept because most
  lines somebody draws are this, and forcing a process meaning onto them would make the other four
  mean less.

## Suggested, never enforced

`natural` reads the roles at both ends and says which of the five that line probably is: out of a
Decision it is a branch, out of an Event a trigger, into a Result a `makes`. That is the whole of
the ergonomics — draw a line from a diamond and it is already a branch.

What it deliberately does not do is **refuse** the others. Somebody sketching a process is
thinking, and a constructor that rejects the line you drew because the boxes are not yet the right
shape is a constructor you fight. `odd_pair` says when a line reads strangely so the console can
mention it; nothing here stops it being drawn.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Kind:
    """One of the five, and the word that goes on the line."""

    name: str
    says: str
    means: str
    # Whether this kind is meaningless without words of its own. Only a branch is: "if" with no
    # condition on it is a fork nobody can follow, while "then" with nothing written on it is
    # exactly as clear as it needs to be.
    wants_words: bool = False
    # Whether the line has a direction that matters. `with` does not — "A goes with B" is the same
    # statement as "B goes with A" — and drawing an arrowhead on it would claim an order that was
    # never said.
    one_way: bool = True


KINDS: dict[str, Kind] = {
    "then": Kind("then", "then", "and after that"),
    "if": Kind("if", "if", "this way, when the condition holds", wants_words=True),
    "when": Kind("when", "when", "this happened, so do that"),
    "makes": Kind("makes", "makes", "and this is what comes out of it"),
    "with": Kind("with", "with", "related, in no particular order", one_way=False),
}

# The line a pair of roles is probably meant to be. Read from the end it leaves, because that is
# what decides it: everything out of a Decision is a branch, whatever it points at.
FROM_ROLE = {"decision": "if", "event": "when"}
INTO_ROLE = {"result": "makes"}
ORDINARILY = "then"


def natural(from_role: str, to_role: str) -> str:
    """Which of the five a line between these two roles probably is.

    A suggestion, and it is applied as a default rather than as a rule — see the module docstring.
    Order matters here: a line out of a Decision *into* a Result is still a branch, because what
    the line is is decided by what it comes out of.
    """
    if from_role in FROM_ROLE:
        return FROM_ROLE[from_role]
    if to_role in INTO_ROLE:
        return INTO_ROLE[to_role]
    return ORDINARILY


def is_a_kind(name: str) -> bool:
    return name in KINDS


def odd_pair(kind: str, from_role: str, to_role: str) -> str:
    """Why this line reads strangely, or an empty string when it does not.

    Never a refusal. Somebody sketching a process is thinking, and the shapes catch up with the
    thought rather than the other way round — but a branch coming out of something that is not a
    decision is usually a card whose role has not been set yet, and saying so is more useful than
    drawing it and hoping.
    """
    if kind == "if" and from_role != "decision":
        return "a branch usually comes out of a Decision"
    if kind == "when" and from_role != "event":
        return "a trigger usually comes out of an Event"
    if kind == "makes" and to_role != "result":
        return "what comes out of a step is usually a Result"
    return ""
