-- Where a project lives, besides on this disk.
--
-- A project is a repository and a checkout, and it is also a Jira board, a GitHub page, a
-- dashboard somebody keeps open. Those are links a human types once and then wants one click
-- away, and nothing on disk can derive them: an `origin` gives a repository, never a tracker.
--
-- What is deliberately not here: credentials. A token in this file is a token in a plain SQLite
-- database that a second application already serves a redacted view out of (docs/07-security.md),
-- with no encryption, no rotation and no audit of who read it. Where a token is ever needed, this
-- table records the *name of the environment variable* it comes from and never the value, so that
-- the secret lives where the operating system already protects secrets and this program can say
-- what it would use without ever holding it.

CREATE TABLE project_link (
    repo_key    TEXT NOT NULL,          -- `origin:owner/repo`, or a path when there is no remote
    name        TEXT NOT NULL,          -- jira | github | dashboard | anything a human types
    url         TEXT NOT NULL,
    token_env   TEXT,                   -- the environment variable, never the token
    added_at    INTEGER NOT NULL,
    PRIMARY KEY (repo_key, name)
);
