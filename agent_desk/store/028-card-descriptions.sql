-- A sentence about one thing on the board, written once and kept.
--
-- "Метадата — созданное ЛЛМ описание элемента, например что представляет из себя проект или чем
-- занята сессия." The board can already say what it *reads*: a status, a branch, a last line. What
-- it cannot say is what a thing *is*, in a sentence somebody who has not been reading the code
-- would understand — and that is exactly the middle of the three views a card has.
--
-- Cached because a board of twenty cards would otherwise be twenty model calls every two seconds.
-- Keyed by the card's own name (`kind:id`), which is how the whole console addresses cards.
--
-- `about` is what the description was written from — the summary, the last line, the branch. When
-- that changes enough, the description is written again; when it has not, the cached one stands.
-- Without it a session's description would be about whatever it happened to be doing on the day
-- somebody first dropped it on the workbench.

CREATE TABLE IF NOT EXISTS card_said (
    name       TEXT PRIMARY KEY,
    said       TEXT NOT NULL,
    about      TEXT NOT NULL DEFAULT '',
    written_at INTEGER NOT NULL
);
