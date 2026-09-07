-- Cards that are only cards, and drawings saved to be used again.
--
-- ## step_card — a box that is just a box
--
-- Until now every card on the workbench stood for something that already existed: a session on
-- this machine, an idea in the pool, a blocker, a folder. That is right for a console you use to
-- look at what is happening, and wrong for a constructor: *"описываем процесс как в лего"* means
-- drawing a step before the thing it will be exists, which there was no card for.
--
-- So a step card is a card with a name and nothing behind it. Its role, its fields, its
-- permissions and its lines all live where every other card's do — keyed by `step:<id>`, the same
-- `kind:id` shape — so nothing else in this program needs to know that this kind is different.
-- That is the whole design: one new row type, and no new path through anything.
--
-- ## template — a drawing kept to be used again
--
-- "Процесс, который собрали один раз, должен запускаться второй раз с другими входами. Иначе
-- конструктор — это одноразовый рисунок."
--
-- A template is a **shape**, not a copy: the roles, what each step says, what each may do, and the
-- lines between them — with the steps numbered rather than named, because the cards a template
-- makes are new cards and cannot be the ones it was saved from.
--
-- `fields` holds one step's answers as JSON, which is the one place a blob is the right shape: the
-- questions differ per role and are expected to change, and a column per field would mean a
-- migration every time a role learns a new one. `store/repo.py` is already the module that parses
-- this program's own JSON (tests/unit/test_structure.py names it), so nothing moves.

CREATE TABLE step_card (
    id       TEXT PRIMARY KEY,
    label    TEXT NOT NULL,
    made_at  INTEGER NOT NULL
);

CREATE TABLE template (
    id       TEXT PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE,
    made_at  INTEGER NOT NULL
);

CREATE TABLE template_step (
    template_id TEXT NOT NULL,
    ord         INTEGER NOT NULL,
    role        TEXT NOT NULL,
    label       TEXT NOT NULL,
    fields      TEXT NOT NULL DEFAULT '{}',
    leave       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (template_id, ord)
);

CREATE TABLE template_line (
    template_id TEXT NOT NULL,
    from_ord    INTEGER NOT NULL,
    to_ord      INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    says        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (template_id, from_ord, to_ord)
);
