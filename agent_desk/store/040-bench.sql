-- The workbench, as a thing in the database rather than a state of a page.
--
-- "Сегодня раскладка помнится в localStorage, а сами карточки при перезагрузке не возвращаются —
-- возвращается только разговор."
--
-- That is exactly what was true: `agent-desk:bench-layout` held where every card was, and nothing
-- held *which cards*. So a reload restored the positions of a bench that was empty. An
-- investigation, a drawing, a prototype and a set of cards laid out by hand all existed until the
-- tab was closed, which makes every scenario that goes off and comes back later impossible — you
-- cannot come back to a surface that is not there.
--
-- One row per card on the surface, keyed by the name every other part of the bench already keys
-- by: `kind:id`, the string that lines, layouts, roles, fields and permissions are all stored
-- against. Nothing here is a second identity for a card.
--
-- Four columns are the page's business and are stored because losing them loses the arrangement,
-- not because the store has an opinion about them: `x`/`y` (where somebody put it), `shown` (folded
-- to a line, or open), and `spent` (already used in a question, so dimmed). `shown` rather than
-- `view`, which is a keyword in SQLite.
--
-- `ord` is where the card is in the stack, and it is an index rather than a clock on purpose. The
-- page sends the whole surface in the order it holds it, and that order is the only thing anyone
-- needs back — a card is restored to coordinates it carries with it, so nothing depends on knowing
-- *when* it was put down. A timestamp here would be the same value on every row of every write.
--
-- What is deliberately NOT here:
--
--   * A note somebody typed on the bench. Its own placeholder promises it "is gone when this tab
--     is" — it is scratch paper, and a promise that specific is not quietly broken by a migration.
--   * A copy taken for a group, a collection, or a ring. Each of those stands for a gesture in
--     progress rather than for a card somebody put down.
--   * The saved workbenches under `agent-desk:benches`. Named benches you switch between are the
--     next idea in this set and want a table with a name in it; this one is about *the* bench
--     surviving a reload, and putting a `bench_id` here now would be a column with one value.
--
-- A block card IS stored, and only for its position: the conversation brings it back by itself
-- from the thread, so restoring it here as well would put two of it on the surface. That is why
-- the page decides what to re-create and the store just says what was there.

CREATE TABLE bench_card (
    name      TEXT PRIMARY KEY,
    kind      TEXT NOT NULL,
    card_id   TEXT NOT NULL,
    label     TEXT NOT NULL DEFAULT '',
    x         INTEGER NOT NULL,
    y         INTEGER NOT NULL,
    shown     TEXT NOT NULL DEFAULT 'hint',
    spent     INTEGER NOT NULL DEFAULT 0,
    ord       INTEGER NOT NULL
);
