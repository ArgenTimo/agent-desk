-- A ticket on somebody's board that says it is stuck (docs/adr/0010).
--
-- Asked for as: "если задача требует человеческого присутствия — оставляют её пока человек не
-- сделает свою работу, а человеческий блокер агент отдельно сохраняет себе в базу".
--
-- Which is the right shape, and worth saying why. A blocked ticket must not go into the queue: an
-- agent started on it would spend a worktree discovering what the ticket already says. And it
-- must not be silently skipped either, because then a board full of blocked work looks exactly
-- like an empty board. So it goes here, and the blockers column shows it.
--
-- `said` is the ticket's own sentence, quoted. This program does not decide that a ticket is
-- blocked; it repeats that the ticket says so, and keeps the key that says where to check
-- (CLAUDE.md, rule five).
--
-- Rows are replaced on every read, so a ticket somebody unblocked stops being a blocker without
-- anybody telling this console.

CREATE TABLE IF NOT EXISTS tracker_blocker (
    key      TEXT PRIMARY KEY,
    repo_key TEXT NOT NULL,
    summary  TEXT NOT NULL,
    said     TEXT NOT NULL,
    seen_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS tracker_blocker_by_project ON tracker_blocker (repo_key);
