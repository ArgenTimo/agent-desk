-- The plan a session's tokens are spent against, and the sessions on it.
--
-- Asked for as four ideas that are one thing: a super-block holding whole projects, a block for a
-- subscription to a service, a percentage in its header saying how close it is to its limit, and
-- the ability to move a session onto a different one for a while.
--
-- **What this console can and cannot know, because the header depends on it.** It cannot read an
-- account's remaining quota: there is no such number on this machine and no API here to ask for
-- one. What it *has* is every session's context size, read from the transcripts it already reads,
-- and the moment a `--resume` was refused for want of budget (docs/adr/0009). So the header shows
-- what this console has observed against a limit a person typed in, and it says which of those two
-- it is — a percentage presented as an account balance would be the guessed status CLAUDE.md's
-- fifth rule is about, wearing a progress bar.
--
-- `limit_tokens` may be null and that is the ordinary state: without it the header shows the
-- number it observed and no percentage, which is honest and still useful.
--
-- A session is on at most one subscription. `until` is what "временно" means — after it, the row
-- is ignored and the session goes back to wherever it was.

CREATE TABLE IF NOT EXISTS subscription (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    service      TEXT NOT NULL DEFAULT '',
    limit_tokens INTEGER,
    created_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS session_subscription (
    short_id        TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL REFERENCES subscription (id) ON DELETE CASCADE,
    until           INTEGER,
    moved_at        INTEGER NOT NULL
);
