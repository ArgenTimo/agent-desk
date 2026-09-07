-- Several tickets in review, all waiting on the same thing, said once (docs/adr/0011).
--
-- Asked for as: "пройди по таблице Jira, собери из комментариев к задачам в колонке In Review все
-- упомянутые блокеры. Сгруппируй их семантически в укрупнённые задачи для человека и к каждой
-- напиши короткий туториал — что конкретно нужно сделать, чтобы разблокировать."
--
-- 026-tracker-blockers.sql holds one row per ticket that says it is stuck, quoted. That is the
-- right shape for a board's own words and the wrong shape for a column of eleven comments which
-- are, between them, three problems: a person reading eleven cards has to do the grouping in
-- their head every time they look.
--
-- So a row here is a **synthesis**, and the two halves are stored apart because they are not the
-- same kind of claim:
--
--   `title` and `tutorial` are a model's writing — a judgement, and the card says so on its face.
--   `said` is the sentences it was made from, each with the key of the ticket it was written on,
--   quoted exactly. Nothing here is believable without that column, which is why it is not null.
--
-- Rows are replaced per project on every pass, so a comment somebody answered stops being a
-- blocker without anybody telling this console — and a pass that could not read the board, or
-- could not reach a model, replaces nothing at all rather than clearing what it failed to check.

CREATE TABLE IF NOT EXISTS review_blocker (
    repo_key TEXT NOT NULL,
    -- A slug of the title, so the card keeps its identity across a pass that groups the same
    -- comments the same way — and with it whatever somebody claimed about it (029-blocker-checking).
    id       TEXT NOT NULL,
    title    TEXT NOT NULL,
    tutorial TEXT NOT NULL,
    said     TEXT NOT NULL,
    seen_at  INTEGER NOT NULL,
    PRIMARY KEY (repo_key, id)
);

CREATE INDEX IF NOT EXISTS review_blocker_by_project ON review_blocker (repo_key);
