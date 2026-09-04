-- A message somebody asked for, waiting for the click that sends it.
--
-- "Tell Biba to test it again" is not a question and not an idea: it is an instruction, and the
-- honest thing to do with one is prepare it and stop. docs/adr/0002 puts the one write path
-- behind a human click, and docs/08-non-goals.md §2 refuses the queue that would decide when a
-- good moment is — so this table holds what would be sent and to whom, and `sent_at` records the
-- click if it ever comes. Nothing here is dispatched by a loop.
--
-- The session is named by the id the registry uses. A session that has ended leaves a row that
-- can no longer be sent, and the console says exactly that rather than quietly dropping it.

CREATE TABLE directive (
    id          TEXT PRIMARY KEY,
    block_id    TEXT NOT NULL REFERENCES block(id),
    session_id  TEXT NOT NULL,
    session_name TEXT NOT NULL,       -- what it was called when it was recorded, for a week later
    text        TEXT NOT NULL,        -- verbatim, ready for the panel of docs/06-console.md
    created_at  INTEGER NOT NULL,
    sent_at     INTEGER
);

CREATE INDEX directive_by_block ON directive (block_id);
