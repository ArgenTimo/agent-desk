-- What happened to an instruction: it was written, and then somebody started an agent on it.
--
-- The `directive` table already held the message and who it was for. Both columns below are about
-- the other ending — the one docs/adr/0006 opened — where a click starts a background agent in
-- that project's checkout instead of waiting for a delivery path that does not exist. `agent_id`
-- is the short id `claude attach|logs|stop` take, and it is what lets the console show the work it
-- caused.

ALTER TABLE directive ADD COLUMN agent_id TEXT;
ALTER TABLE directive ADD COLUMN dispatched_at INTEGER;
