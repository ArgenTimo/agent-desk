-- The names a person uses for things, so an agent can be told what they mean.
--
-- "Верстак", "the pool", "a blocker", "DuckyFlow staging" — every project grows a vocabulary, and
-- an agent dispatched into one does not have it. Today that costs a paragraph of explanation in
-- every instruction, or a wrong guess.
--
-- A term and what it means, per project. Deliberately not a taxonomy: no types, no aliases, no
-- hierarchy. It is a list somebody writes because they are tired of explaining the same word, and
-- it is worth exactly what it costs to write.
--
-- The empty `repo_key` is the one every project gets: words that mean the same thing everywhere.

CREATE TABLE IF NOT EXISTS glossary (
    id         TEXT PRIMARY KEY,
    repo_key   TEXT NOT NULL DEFAULT '',
    term       TEXT NOT NULL,
    means      TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS glossary_by_project ON glossary (repo_key);
