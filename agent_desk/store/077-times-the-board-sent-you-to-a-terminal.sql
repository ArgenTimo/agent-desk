-- The half of the roadmap's first measure that this console can actually stand behind.
--
-- docs/09-roadmap.md ends with `What is measured`, and it is unambiguous about why those two:
--
--     Two numbers, from the beginning, because they are the ones that say whether this worked:
--       * Terminal opens to check status, per day. Phase 1 exists to drive this to zero.
--       * Ideas captured, and of those, promoted.
--
-- The second has been derivable from `idea` since the beginning and was never shown. The first was
-- never recorded at all, and it cannot be — a terminal somebody opens themselves is not a thing
-- this program can see, and an estimate of it would be a guessed status wearing a number
-- (CLAUDE.md, rule five).
--
-- What it *can* see is every terminal it opened. `go to it` calls `opening.open_it`, and each press
-- is this console handing somebody back to a terminal because the board did not answer their
-- question. That is a different number from the roadmap's and it is the honest half of it, so it is
-- stored under a name that says which it is rather than under the roadmap's word.
--
-- ## One row per press, and no aggregate
--
-- A count kept as a running total is a count nobody can ask a new question of: "this week" and "on
-- that project" are both answerable from rows and neither is answerable from a number. There will
-- be a few of these a day at most, which is not a table that needs a shape.
--
-- `session_id` rather than a project key: the project is derived from the session's directory
-- everywhere else in this program, and storing it here would be a second answer to which project a
-- session is in.
--
-- Nothing here records *why* somebody pressed it. That is the thing worth knowing and it is not
-- knowable, and a column for it would fill up with an empty string.

CREATE TABLE went_to_a_terminal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    at INTEGER NOT NULL
);

CREATE INDEX went_to_a_terminal_at ON went_to_a_terminal (at);
