-- What anybody working in this project should know, besides the thing they were asked to do.
--
-- The second entity the owner asked for, next to the ideas: an idea is a thing somebody *had*,
-- and this is a thing that is simply true — the conventions, the wishes, the "we do not use X
-- here", the "always run Y before you finish". It is not a backlog item, it will never be built,
-- and it does not belong in a list of things to do.
--
-- One row per project and one body of text, because that is what it is. Splitting it into fields
-- would be inventing a schema for prose nobody has written yet, and the value of this is that it
-- goes into every agent this console starts in that project — verbatim, under a heading that says
-- where it came from.

CREATE TABLE IF NOT EXISTS project_note (
    repo_key   TEXT PRIMARY KEY,
    body       TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL
);
