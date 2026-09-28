-- Why somebody went to a terminal, in their words — one of four (B4 in _research/06_backlog.md).
--
-- 077 said the reason "is not knowable, and a column for it would fill up with an empty string".
-- Both halves were true of a reason this program would have to *infer*. This one is asked: after
-- `go to it` has opened the terminal, the board offers four words and the person may press one.
-- It is a fact somebody stated, not a status guessed from silence (CLAUDE.md, rule five), and a
-- press nobody labelled stays '' — which is itself the honest answer, "not said".
--
-- The four, closed rather than free text, because the point is to count them: to answer a
-- question, to approve a tool, to read what it did, something else. `agent_desk/opening.py` holds
-- the list; a word outside it is refused by the route rather than stored.

ALTER TABLE went_to_a_terminal ADD COLUMN reason TEXT NOT NULL DEFAULT '';
