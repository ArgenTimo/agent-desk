-- A ticket on somebody's board, as a thing that can be looked at.
--
-- "И способ попросить: «покажи тикеты из спринта», «покажи открытые PR-ы»."
--
-- The console has read boards since docs/adr/0010 and has had exactly one thing to do with what it
-- read: put the unblocked ones in its own queue as tasks, and the blocked ones in the blockers.
-- Both are *decisions about* a ticket. Neither is the ticket, and "покажи тикеты" asks for the
-- ticket — the rows as the board has them, including the ones already queued and the ones nobody
-- will start.
--
-- ## Why not read them out of `task`
--
-- Because a task is this console's decision to do the work, and a ticket is somebody else's
-- decision that the work exists (docs/adr/0005 draws exactly this line and docs/adr/0010 keeps it).
-- A board read where nothing was queued — every ticket already in the queue, or every one blocked —
-- would show nothing, and "your board is empty" is a different claim from "there is nothing new
-- here for me to start".
--
-- ## Same shape as `pull`, and for the same reasons
--
-- A copy of somebody else's list, replaced whole on every read, keyed by (repo_key, key) because a
-- ticket key means nothing outside the board it is on. Read-only: nothing here transitions,
-- comments on, assigns or closes anything.

CREATE TABLE ticket (
    repo_key   TEXT NOT NULL,
    key        TEXT NOT NULL,
    summary    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT '',
    blocked_by TEXT NOT NULL DEFAULT '',
    seen_at    INTEGER NOT NULL,
    PRIMARY KEY (repo_key, key)
);
