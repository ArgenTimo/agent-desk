-- A blocker somebody says is cleared, waiting for that to be checked.
--
-- "Человек может нажать кнопку «разблокировано» — блокер остаётся, но переходит в статус
-- уточнения; агенты запускают проверку в ближайший момент когда освободятся, проверяют блокер, и
-- только если разблокировано — блок уходит."
--
-- The button does not delete anything, and that is the whole design. A blocker that vanished
-- because somebody pressed a button is a blocker that comes back as a surprise two hours later,
-- when the agent that was waiting on it fails for the same reason. So pressing it records a
-- *claim*, the card says a claim has been made, and the blocker only goes when something checked.
--
-- Keyed by the blocker's own name (`kind:ref`), which is how the column already addresses them —
-- and which is recomputed rather than stored, so a row here for something that is no longer stuck
-- simply never matches anything and is harmless.

CREATE TABLE IF NOT EXISTS blocker_claim (
    name       TEXT PRIMARY KEY,
    said       TEXT NOT NULL DEFAULT '',
    claimed_at INTEGER NOT NULL,
    checked_at INTEGER,
    -- What the check found, in its own words. Null while nobody has looked.
    found      TEXT
);
