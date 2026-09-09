-- A card hung on the output that says one of two things about it.
--
-- "Временный блок-проверка, в первой итерации берёт вводный вопрос/карточку + то что мы получили от
-- сервиса и возвращает одно из двух: 1 — всё корректно, 2 — вернулась какая-то дичь."
--
-- Two inputs and one verdict. The inputs are not two separate joins: an answer card already carries
-- both halves of its exchange — what was asked is the block's input and what came back is its
-- answer — so a check joined to one answer card has everything it needs. That is why this reaches
-- through the same line a button reaches through (059) rather than inventing a second kind of wire.
--
-- ## Two ways to decide, and the card says which
--
-- `agent_desk/checking.py` already reads four forms a machine can settle for nothing: contains,
-- does not contain, is JSON, shorter than N. Anything else is a judgement, and the only thing here
-- that can make one is the answer engine. "It passed" from a regular expression and "it passed"
-- from a model are not the same claim, so `judged` records which was used — a person acting on
-- either deserves to know which they have.
--
-- ## Why the verdict is stored and not recomputed
--
-- A check is about one answer at one moment. Recomputing it on every render would re-ask the model
-- on every page load, and a check that quietly changes its mind between refreshes is worse than no
-- check. `at` is when it was decided, so a verdict about an answer that has since been replaced can
-- be seen to be old rather than trusted as current.

CREATE TABLE check_card (
    id      TEXT PRIMARY KEY,
    label   TEXT NOT NULL,
    said    TEXT NOT NULL DEFAULT '',
    -- '', 'passed' or 'failed'. Empty is "nobody has pressed it", which is not a third verdict:
    -- it is the absence of one, and it renders as a card waiting rather than as a card unsure.
    verdict TEXT NOT NULL DEFAULT '',
    why     TEXT NOT NULL DEFAULT '',
    judged  INTEGER NOT NULL DEFAULT 0,
    at      INTEGER NOT NULL DEFAULT 0,
    made_at INTEGER NOT NULL
);
