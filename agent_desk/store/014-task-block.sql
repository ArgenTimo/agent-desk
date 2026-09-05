-- Which message a task came from.
--
-- It was matched by comparing the task's title to the first sixty characters of the block's input,
-- which worked until two messages started the same way and would then have shown one block the
-- other's work. A task belongs to the message that asked for it; the column says so.

ALTER TABLE task ADD COLUMN block_id TEXT REFERENCES block(id);

CREATE INDEX task_by_block ON task (block_id);
