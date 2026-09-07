-- What a step may do, and what it produced.
--
-- Two tables, one migration, because they are the two halves of the same sentence from the first
-- user's feedback: "под капотом контекст + агент + тулзы + пермишены + память".
--
-- ## card_leave — what one step is allowed to do
--
-- A row per permission granted, rather than a column per permission: the list in
-- agent_desk/allowed.py is expected to grow as this console learns to enforce more, and a schema
-- change per switch is how a permission ends up being added without anybody checking whether
-- anything actually reads it.
--
-- Nothing granted is not the same as everything refused — a step nobody has touched runs the way
-- every task this console already starts (allowed.NATURALLY). The rows are for narrowing or
-- widening that deliberately.
--
-- ## card_made — what a step produced
--
-- "Result одного шага должен быть входом для следующего, иначе схема из пяти блоков — это пять
-- независимых запросов."
--
-- The latest only. A history of every result a step ever produced is a different feature with a
-- different question behind it ("what did this do last Tuesday"), and the thing that makes a
-- sequence a sequence is what the step in front of this one produced *this time*. When runs exist
-- and need their own record, that is a table with a run id in it, not a column bolted onto this
-- one.

CREATE TABLE card_leave (
    name    TEXT NOT NULL,
    leave   TEXT NOT NULL,
    set_at  INTEGER NOT NULL,
    PRIMARY KEY (name, leave)
);

CREATE TABLE card_made (
    name    TEXT PRIMARY KEY,
    made    TEXT NOT NULL,
    at      INTEGER NOT NULL
);
