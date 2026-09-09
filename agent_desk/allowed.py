"""What one step of a process is allowed to do, and which of those this console can actually hold.

From the first user's feedback: *"у шага должно быть видно и настраиваемо, что ему можно: только
читать, писать в свою ветку, ходить в сеть, трогать конкретный проект. Это то, что отличает
конструктор, которому можно доверить запуск, от схемы, которую страшно нажать."*

He is right about what it is for, and the whole value of it rests on a distinction that a
permissions screen usually hides: **some of these this program enforces, and some of them it can
only ask for.** A row of switches that look alike but do not work alike is worse than no switches
at all — it is the guessed status CLAUDE.md's fifth rule is about, wearing a checkbox.

So each one carries `held`, and there are exactly two values:

- **`enforced`** — this console does the thing or refuses to. Not starting an agent, starting it
  in one directory rather than another, calling `land.land` or not, passing `push=False`. Every
  one of these is a branch in this program's own code, and the switch is what the branch reads.
- **`asked`** — it goes into the briefing the agent is given, in words. An agent that ignores it
  is not stopped by anything here. That is a real and useful thing to be able to say to a step;
  it is not a guarantee, and the card says so rather than implying otherwise.

The list is short because it is only as long as the things this program genuinely does. A
permission for something nothing here reads would be a switch that does nothing, which is the
failure this docstring exists to prevent.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Leave:
    """One thing a step may do."""

    name: str
    says: str
    means: str
    # `enforced` or `asked`. See the module docstring: the difference between the two is the point
    # of the field, and a card that showed them identically would be lying by omission.
    held: str
    # What actually makes it true — a branch in this program, or a sentence in a briefing. Shown
    # on the card, because "how do you know" is the question a permission invites.
    how: str


ALLOWED: dict[str, Leave] = {
    "read": Leave(
        name="read",
        says="read the project",
        means="look at the code and answer, without an agent that can change anything",
        held="enforced",
        how="the step is run as a question, so no worktree and no agent are started at all",
    ),
    "work": Leave(
        name="work",
        says="work in its own copy",
        means="an agent in a worktree of its own, which nothing else shares",
        held="enforced",
        how="`claude --bg -w`, and the observed checkout is never written to (CLAUDE.md, rule 2)",
    ),
    "land": Leave(
        name="land",
        says="offer it to the gate",
        means="put the branch in front of the project's own gate when the work is finished",
        held="enforced",
        how="this console calls the landing, or does not — and a failing gate merges nothing",
    ),
    "push": Leave(
        name="push",
        says="push the branch",
        means="send the branch to the remote once it has landed",
        held="enforced",
        how="the landing is asked to push, or asked not to",
    ),
    # "У Action есть разрешения; добавить среди них «это делает человек» — и шаг встаёт в очередь к
    # человеку, показывает, что от него нужно, ждёт нажатия и отдаёт результат дальше по цепочке."
    #
    # It belongs here rather than beside the roles because it is a fact about *this step*, not a
    # sixth kind of thing: the same Action, done by a person. And it is enforced in the strongest
    # sense any of these are — no agent is started, so there is nothing to obey or ignore.
    #
    # Without it every real process stops at the first approval. With it a drawing describes the
    # whole of a piece of work rather than the part machines do.
    "hands": Leave(
        name="hands",
        says="a person does this one",
        means="wait for somebody to do it and say so, rather than starting anything",
        held="enforced",
        how="the run holds at this step and no agent is started at all",
    ),
    "net": Leave(
        name="net",
        says="reach the network",
        means="fetch things it does not already have",
        held="asked",
        how="written into the briefing in words; nothing here can stop an agent that ignores it",
    ),
}

# What a step may do when nobody has said. Its own copy and nothing further: that is what this
# console does today when somebody presses build, and everything past it — merging, pushing —
# is a thing somebody should have to say out loud.
NATURALLY: tuple[str, ...] = ("work",)


# What a step is allowed when its work is a prompt (01M1X8DA8XDSQ16N5DVDVZGM5X). Reading, and
# nothing else, and not as a default: *"Шаг-промпт по определению имеет право только читать: ни
# ветки, ни гейта, ни пуша… нужно, чтобы для этой роли оно было не настройкой по умолчанию, а тем,
# что нельзя выключить."*
#
# The difference between a default and a rule is the whole of that sentence. A default is the
# switch's starting position and somebody can move it; this is what the step *is*. A prompt that
# could be given a worktree and a push is not a pipeline step that happens to be configured
# safely — it is an agent with a prompt in its briefing, which the console already has and calls
# something else.
ISOLATED: tuple[str, ...] = ("read",)


def leave_for_a_prompt() -> tuple[str, ...]:
    """What a step whose work is a prompt may do. Not read from anywhere, because there is nowhere
    it could be written down that somebody could not then edit."""
    return ISOLATED


def is_a_prompt(said: object) -> bool:
    """Whether this card's work is a prompt, from what it says about itself.

    One reader, so that "is this a pipeline step" has one answer. Two would eventually disagree,
    and the direction they would disagree in is a prompt step running with a worktree.
    """
    asks = getattr(said, "get", lambda _name, _default="": "")("asks", "")
    return bool(str(asks or "").strip())


def is_allowed(name: str) -> bool:
    return name in ALLOWED


def leave_for(given: Iterable[str] | None) -> tuple[str, ...]:
    """The permissions a step has: what was granted, or the default when nothing was.

    Nothing granted is not the same as everything refused. A step nobody has touched runs the way
    every task this console starts already runs, and the switches are for narrowing or widening
    that deliberately.
    """
    if not given:
        return NATURALLY
    kept = tuple(one for one in given if one in ALLOWED)
    return kept or NATURALLY


def enforced(names: tuple[str, ...]) -> tuple[str, ...]:
    """Of these, the ones this program actually holds."""
    return tuple(one for one in names if ALLOWED[one].held == "enforced")


def only_asked(names: tuple[str, ...]) -> tuple[str, ...]:
    """And the ones it can only put in the briefing."""
    return tuple(one for one in names if ALLOWED[one].held == "asked")


def reads_only(names: tuple[str, ...]) -> bool:
    """Whether this step may not start an agent that can change anything.

    `read` and `work` are the two answers to one question — is there an agent in a worktree — so
    `read` wins when both are somehow set: the narrower reading of an ambiguous permission is the
    only safe one, and this is the branch that decides whether a process can write to disk.
    """
    return "read" in names
