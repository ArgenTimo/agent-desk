-- A line between two cards, and what it means (agent_desk/ties.py).
--
-- From the first user's feedback: "дальше создаём процесс взаимодействия между". The lines the
-- workbench could already draw were of two sorts and neither of them is this:
--
--   * `idea_link` (024) joins one *idea* to another and says `needs` or `touches`. It is about the
--     pool — what has to be built before what — and it cannot name a session, a blocker or a
--     folder, because its columns are idea ids with a foreign key behind them.
--   * The page's own lines, held in the script, which say things like "asked about" and vanish
--     when the tab does. They are a record of what happened, not something somebody drew.
--
-- A process needs a third: any card to any card, typed with what happens between them, and kept.
-- Hence names rather than ids — `kind:id`, the same string the layout, the roles and the ties
-- already use — so a line can join an idea to a session without this table growing a column per
-- kind of thing that exists.
--
-- `says` is the words on the line, and only a branch really needs them: "if" with no condition on
-- it is a fork nobody can follow. It is a column rather than a rule because the other four are
-- allowed to carry a note and often should.
--
-- No foreign key, deliberately. The things at the two ends live in four different places and one
-- of them — a session — is not in this database at all. A line to a card that has gone is a line
-- the workbench does not draw, which is exactly what it did before this table existed
-- (agent_desk/ideas/bench.py: a relation with one end off the bench is not drawn).

CREATE TABLE card_tie (
    id          TEXT PRIMARY KEY,
    from_name   TEXT NOT NULL,
    to_name     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    says        TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL
);

-- One line between the same two cards in the same direction. Drawing it twice is somebody
-- pressing twice, not two relations.
CREATE UNIQUE INDEX card_tie_pair ON card_tie (from_name, to_name);
