-- The same card can be on two workbenches, and until now that was a 500.
--
-- 044 gave every chat its own bench and added `thread_id` to the rows. What it did not do is move
-- the primary key, which is still `name` alone — so the moment the same idea was put on the bench
-- of two chats, the second write failed on a uniqueness constraint. The page sends the whole
-- surface, so the failure was not one card: the entire bench stopped saving, silently, for as long
-- as the two chats both held that card.
--
-- Found by dragging a project card onto a second chat's bench in a browser and watching nothing
-- persist. It is invisible from the page — the write is fire-and-forget by design, so a 500 there
-- looks exactly like a console that is working.
--
-- The key is the pair. A card is on *a* bench at a place, and which bench is half of what it is.
--
-- SQLite cannot move a primary key with ALTER, so the table is rebuilt — the one shape of
-- migration this schema has not needed before. Everything is copied; nothing is dropped, because
-- the old key was strictly narrower than the new one and no two rows can collide on the way over.
--
-- The two indexes from 044 go with it: `bench_card_thread` is now the leading half of the primary
-- key, so SQLite has it already and a second copy of it would be a second thing to keep.

CREATE TABLE bench_card_new (
    thread_id TEXT    NOT NULL DEFAULT '',
    name      TEXT    NOT NULL,
    kind      TEXT    NOT NULL,
    card_id   TEXT    NOT NULL,
    label     TEXT    NOT NULL DEFAULT '',
    x         INTEGER NOT NULL,
    y         INTEGER NOT NULL,
    shown     TEXT    NOT NULL DEFAULT 'hint',
    spent     INTEGER NOT NULL DEFAULT 0,
    ord       INTEGER NOT NULL,
    by_hand   INTEGER NOT NULL DEFAULT 0,
    came      TEXT    NOT NULL DEFAULT '',
    came_at   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (thread_id, name)
);

INSERT INTO bench_card_new
    (thread_id, name, kind, card_id, label, x, y, shown, spent, ord, by_hand, came, came_at)
SELECT thread_id, name, kind, card_id, label, x, y, shown, spent, ord, by_hand, came, came_at
  FROM bench_card;

DROP TABLE bench_card;
ALTER TABLE bench_card_new RENAME TO bench_card;
