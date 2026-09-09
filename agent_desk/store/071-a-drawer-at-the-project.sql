-- A drawer for drafts and small scripts, attached to a project rather than to a conversation.
--
-- «Три раза за смену я писал заново одни и те же три скрипта, потому что каталог сессии исчезает
-- вместе с сессией. Место, привязанное к проекту, а не к разговору, стоит одну таблицу.»
--
-- A session's scratch directory dies with the session. The helper that lists the open ideas, the
-- one that closes them against a commit, the one that prints a single idea in full — all three were
-- written from scratch three times in one shift, and all three were the same three scripts.
--
-- ## This is not the repository, and that is the whole rule
--
-- «Сюда пишет только консоль.» The second of the five rules in CLAUDE.md is that this program never
-- writes anything into an observed repository or its worktree. A drawer of scripts is exactly the
-- shape that rule exists to refuse if it lands on disk next to somebody's code — so it does not
-- land on disk at all. The body is a column. Reading one out and running it is the caller's act, in
-- the caller's own tree, and this console never learns that it happened.
--
-- ## Why the name is the key
--
-- The thing being replaced is a filename. `open_ideas.py` is what somebody types, remembers and
-- overwrites, and a drawer where writing the same name twice made two rows would be a drawer with
-- four versions of one script in it by lunchtime. So writing an existing name replaces it, which is
-- what saving a file does.
--
-- ## Why it is per project and empty means every project
--
-- A script that lists the ideas of this console is not useful in another checkout, and a project
-- with forty scripts in it that belong to something else is a drawer nobody opens. The empty key is
-- a real answer rather than a missing one: some scripts are about no project in particular.

CREATE TABLE scratch (
    name        TEXT NOT NULL,
    project_key TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL,
    made_at     INTEGER NOT NULL,
    PRIMARY KEY (project_key, name)
);
