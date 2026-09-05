-- An idea that was filed somewhere, and what it was filed as.
--
-- One row per idea that made it out through the door of docs/adr/0005. It exists so that a second
-- click cannot file the same thought twice and so that the card can show where the thought went —
-- which is the whole of what this program knows about it afterwards. Nothing here is kept in step
-- with the tracker: status, comments and transitions are Jira's to answer, and asking it would
-- make this a tracker client rather than a notebook that can post once.

CREATE TABLE filing (
    id          TEXT PRIMARY KEY,
    idea_id     TEXT NOT NULL REFERENCES idea(id),
    tracker     TEXT NOT NULL,          -- `jira` today, and the column exists so it need not be
    issue_key   TEXT NOT NULL,
    url         TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);

CREATE UNIQUE INDEX filing_one_per_idea ON filing (idea_id);
