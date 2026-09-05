-- The environment a project's agents need, by name.
--
-- Not a `.env` file, and deliberately: writing one would be this program editing a repository it
-- watches, which is CLAUDE.md's second rule and the reason the ideas module produces drafts rather
-- than commits. What is kept here is the *list of variable names* that matter for this project —
-- the console can then say which of them the shell it was started from actually has, before an
-- agent is dispatched into a repository and discovers the answer the hard way.
--
-- No values. Same reason as project_link.token_env: a plain SQLite file with no encryption, in a
-- process that serves a page to other people (../docs/07-security.md).

CREATE TABLE project_env (
    repo_key    TEXT NOT NULL,
    name        TEXT NOT NULL,          -- the variable, never its value
    note        TEXT,                   -- what it is for, in a human's words
    added_at    INTEGER NOT NULL,
    PRIMARY KEY (repo_key, name)
);
