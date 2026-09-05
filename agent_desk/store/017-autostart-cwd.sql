-- Where a project that may act on its own actually is.
--
-- The queue's tasks each carry their own directory, because a person queued them from a page that
-- knew it. An exploration has no task to inherit one from — it *is* the first task — so the
-- checkout is recorded when the switch is pressed, by the panel that already knows which project
-- the button belongs to (docs/adr/0008).
--
-- Without this the loop could only explore a project it had run something in before, which is
-- exactly the project that least needs looking at.

ALTER TABLE autostart ADD COLUMN cwd TEXT;
