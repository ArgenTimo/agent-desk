-- A project a human decided on, over the top of what the repositories say.
--
-- By default a project *is* a repository: every checkout that resolves to one origin is one
-- project, and nobody has to say so. That default is wrong for exactly the case the owner of this
-- machine described — an API and an iOS app in two repositories that are obviously one product —
-- so a grouping can be declared, and it names repositories rather than folders because a folder
-- is a checkout of a repository and moving one without the other would mean nothing.
--
-- Deleting a group returns its members to their own repositories. Nothing is lost by ungrouping.

CREATE TABLE project_group (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);

CREATE TABLE project_member (
    group_id    TEXT NOT NULL REFERENCES project_group(id),
    repo_key    TEXT NOT NULL,
    added_at    INTEGER NOT NULL,
    PRIMARY KEY (group_id, repo_key)
);

CREATE INDEX project_member_by_repo ON project_member (repo_key);
