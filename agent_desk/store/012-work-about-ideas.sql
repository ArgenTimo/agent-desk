-- Which ideas a message was about, and when the work started for one finished.
--
-- Two halves of the same sentence: "if the request touches ideas, say so — and when the idea is
-- built, it leaves the list" (../docs/05-ideas.md).
--
-- `block_idea` is what the console shows against a message: these are the thoughts it is about, as
-- far as one short run could tell. It is a guess, and it is rendered as an offer — a button — not
-- as a fact.
--
-- `task.finished_at` is what closes the loop. A dispatched agent has no way to report back, and
-- this program will not ask it to; what it can see is that the session is gone from the registry.
-- That is the moment the ideas that task was dispatched *for* are marked built, and a human who
-- finds it was not, after all, presses Keep.

CREATE TABLE block_idea (
    block_id    TEXT NOT NULL REFERENCES block(id),
    idea_id     TEXT NOT NULL REFERENCES idea(id),
    PRIMARY KEY (block_id, idea_id)
);

ALTER TABLE task ADD COLUMN finished_at INTEGER;
