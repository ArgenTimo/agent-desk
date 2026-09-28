-- A card that is a picture of something the project actually has.
--
-- «Нарисуй мне схему базы данных текущего проекта», «создай мне матрицу фич и что они закрывают» —
-- and, in the same breath, «не делай фичи именно под эти 2 примера, а реализуй гораздо гибче».
--
-- The drawing branch could already draw things as well as processes (the second vocabulary,
-- tests/unit/test_draw_anything.py), but a drawn thing became a step card: a name, the role
-- `object`, and one two-line `what`. A table with its columns, a feature with what it covers, a
-- service with its endpoints — none of those fit in a name and two lines, so a drawing of a real
-- project came out as a handful of labels.
--
-- ## One new row type, and no new path through anything
--
-- The same argument 038 made for `step_card`. A sketch is keyed `sketch:<id>`, the `kind:id` shape
-- every card has, so its role, its lines to other cards and its place on a bench all live where
-- every other card's do and nothing else needs to know this kind is new.
--
-- ## Why `kind` is free text here when roles are not
--
-- roles.py argues against a free-form field, and the argument is about *executing* a card: a field
-- an engine reads must be one of a small set. A sketch is not executed. Its kind word — `table`,
-- `feature`, `service`, `endpoint` — is a label read by a person, and a closed list of them would be
-- precisely the "feature for these two examples" the author asked not to be built. What *is* closed
-- is its role (always a thing that exists, `object`) and the kind of line between two of them
-- (`named`, whose words are the relation), so nothing that reasons about a drawing has to reason
-- about free text.
--
-- ## `lines`, and `read_from`
--
-- `lines` is the detail, one entry per line, newline-joined: a column and its type, a thing a
-- feature covers. Bounded where it is read (agent_desk/telling.py), not here.
--
-- `read_from` is where in the project this was seen — a path, when the drawing said one. A picture
-- of a project is a claim about that project, and a claim that carries where it was read is one
-- somebody can check (CLAUDE.md, rule five).

CREATE TABLE sketch_card (
    id        TEXT PRIMARY KEY,
    kind      TEXT NOT NULL,
    label     TEXT NOT NULL,
    lines     TEXT NOT NULL DEFAULT '',
    read_from TEXT NOT NULL DEFAULT '',
    made_at   INTEGER NOT NULL
);
