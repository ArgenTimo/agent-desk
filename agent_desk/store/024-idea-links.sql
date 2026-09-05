-- How one idea relates to another, when it is not a sub-idea of it.
--
-- Grouping already exists: `parent_id` says "this is part of that". It cannot say the two things
-- the owner asked for.
--
-- `needs` — a direct dependency. Doing this one first is wasted or impossible. Not a sub-idea:
-- both are whole ideas, and either could be built by somebody who never heard of the other.
--
-- `touches` — an indirect link. Each works on its own exactly as expected, and building both
-- produces something neither describes. That third thing is the reason to record it: it is
-- invisible in a flat list and it is the most valuable thing in the pool.
--
-- Directed, because both of these are: A needs B is not B needs A, and even `touches` is written
-- from somewhere. A pair is stored once and read from both ends.

CREATE TABLE IF NOT EXISTS idea_link (
    id         TEXT PRIMARY KEY,
    from_id    TEXT NOT NULL REFERENCES idea (id) ON DELETE CASCADE,
    to_id      TEXT NOT NULL REFERENCES idea (id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idea_link_once ON idea_link (from_id, to_id, kind);
CREATE INDEX IF NOT EXISTS idea_link_to ON idea_link (to_id);
