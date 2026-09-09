"""Drawings that come with the console.

*«Шаблон из двух шагов: первый работает в своей копии, второй имеет только `read`, получает на вход
то, что вышло, и говорит «годится» или «вот что не так»… Это не новая механика: разрешения, память
шага и очередь уже есть. Это шаблон, который можно положить в коробку и который сразу делает
автономную работу заметно безопаснее.»*

Every part of the review pair already worked. What did not exist is the arrangement — and an
arrangement nobody has drawn is one nobody uses, which is the whole distance between "this is
possible" and "this is what happens by default".

## In code, not in the table

The first version put it in the store as a migration, and seven tests failed on the same sentence:
`templates() == []`. They were right and the migration was wrong. "Saved processes" means the ones
*you* saved, a list that starts empty is part of that meaning, and a row somebody never saved
sitting in it — which `forget` would then delete for ever — is a worse answer than a slightly longer
route.

So a boxed drawing is a constant. It is offered in the same list, used by the same press, and
cannot be deleted, because there is nothing to delete: using one makes fresh cards exactly as a
saved one does.
"""

from __future__ import annotations

from agent_desk.store.repo import Template, TemplateLine, TemplateStep

# "Первый работает в своей копии, второй имеет только `read`." The permission is what makes this
# safer rather than the words: `read` means no worktree and no agent at all — the step is asked as
# a question (`agent_desk/allowed.py`). A reviewer that could write is a second author, and two
# authors and no reader is the arrangement this replaces.
REVIEW_PAIR = Template(
    id="boxed:review-pair",
    name="make it, then check it",
    made_at=0,
    steps=(
        TemplateStep(
            ord=1,
            role="action",
            label="do the work",
            fields={
                "do": "Make the change that was asked for. Work in your own copy, "
                "and do not merge or push."
            },
            leave=("work",),
            dx=0,
            dy=0,
        ),
        TemplateStep(
            ord=2,
            role="action",
            label="read it back",
            fields={
                # Its permission already stops it. Saying so as well is the belt-and-braces every
                # other permission gets in a briefing: an agent that knows it may not will not
                # spend a turn trying.
                "do": "Read what the step before you produced. Say “it will do” and nothing else, "
                "or say exactly what is wrong with it. Change nothing — you are reading, "
                "not fixing."
            },
            leave=("read",),
            dx=0,
            dy=200,
        ),
    ),
    lines=(TemplateLine(from_ord=1, to_ord=2, kind="then", says="when the work is done"),),
)

BOXED: tuple[Template, ...] = (REVIEW_PAIR,)


def named(name: str) -> Template | None:
    """The boxed drawing with this name, or `None`."""
    return next((one for one in BOXED if one.name == name), None)
