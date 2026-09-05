-- A project that may go looking for something to fix when its queue is empty (docs/adr/0008).
--
-- A second switch rather than a wider one: arming the queue says "start what I put here", and
-- this says "and when there is nothing, find something". Those are different decisions, so they
-- are made separately and a project can be armed without being this.
--
-- `explored_at` is the last time it went looking, and it is what the day's budget is counted
-- against — a budget in days rather than hours, because exploration is not urgent by definition.

ALTER TABLE autostart ADD COLUMN exploring_at INTEGER;
ALTER TABLE autostart ADD COLUMN per_day INTEGER NOT NULL DEFAULT 3;
