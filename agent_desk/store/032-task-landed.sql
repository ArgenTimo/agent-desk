-- Whether the gate passed, and not only what it said about it.
--
-- `task_landed` recorded `Landed.detail` — a sentence — and threw away `Landed.landed`, the
-- boolean the sentence describes. That was enough while the only reader was a card somebody
-- reads, and it is not enough for `waking.py`'s "после того как пройдёт гейт": a condition that
-- has to grep a sentence for the word "merged" is a condition that goes wrong the first time the
-- wording changes, and this repository already has a rule about depending on the shape of prose
-- (docs/adr/0004).
--
-- Three states, which is why it is nullable rather than a default of 0: landed, did not land, and
-- **nothing tried** — most tasks never offer a branch to anything. A project whose gate has never
-- run is not a project whose gate is green, and that difference is the whole of what this column
-- is for (CLAUDE.md, the fifth rule).

ALTER TABLE task ADD COLUMN landed INTEGER;
