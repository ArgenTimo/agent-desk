-- One place for the handful of choices a person makes about this console itself.
--
-- Not a settings system: a key and a value, for the things that are neither a fact about a session
-- nor a thought somebody wrote down. The first is how the ideas column is sorted, which has to
-- survive a server-sent event replacing the column two seconds later — so it cannot live in a
-- query parameter, and a single-user tool with one SQLite file has no better place for it than
-- the file.
--
-- Anything that grows a second dimension — per project, per viewer — is not this table.

CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
