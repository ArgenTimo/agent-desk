-- What the model calls cost, so that the answer to "how much is this costing" is not "wait until
-- the statement arrives".
--
-- "У автозапуска есть бюджет в час на агентов. У вызовов модели нет ничего. Сценарии 7 и 10 — это
-- десятки вызовов подряд, а 8 и 11 — вызов на каждое нажатие. Нужен видимый счётчик (сколько
-- потрачено за сегодня) и потолок, при достижении которого консоль останавливается и говорит, а не
-- продолжает. Это та вещь, отсутствие которой обнаруживается в конце месяца."
--
-- The last sentence is why this is a table rather than a number in memory. A tally that resets
-- when the console restarts is a ceiling that `--reload` walks straight through, and this console
-- is normally run with `--reload`.
--
-- ## Where the number comes from
--
-- The CLI reports it. Every `claude -p --output-format stream-json` run ends with a `result` event
-- carrying `total_cost_usd`, which is what that run actually cost — cache reads, several models
-- within one run, and the sub-agents it spawned, all of it already added up by the thing that did
-- the spending. This console does not compute a price, does not know a rate card, and does not
-- decide anything differently because of a number: it records what it was told and shows it.
--
-- Like every other shape read out of the CLI, `total_cost_usd` is not a contract (docs/adr/0004).
-- A run that does not report one is recorded as nothing rather than as a guess, and the counter
-- says so by not moving — which is the honest reading of "the run did not say".
--
-- ## One row per call, not a daily total
--
-- A running total in a single row cannot answer "when did that happen", cannot be recomputed after
-- a bug, and has to decide what a day is at write time — which is the wrong end, because the day
-- is a question about the reader's clock and the row is a fact about a moment. Rows are small and
-- there are a few hundred a day at the very most.

CREATE TABLE spend (
    id  TEXT PRIMARY KEY,
    at  INTEGER NOT NULL,
    usd REAL NOT NULL
);

CREATE INDEX spend_at ON spend (at);
