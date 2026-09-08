-- What one step of one run cost, and how long it took.
--
-- "Токены, деньги, секунды. Для разработчика это половина смысла: промпт, который лучше на 3% и
-- дороже вдвое, — это плохой промпт, и увидеть это надо на схеме, а не в счёте в конце месяца."
--
-- 043 counts what the console spends in a day and stops at a ceiling. That is a fuse, and a fuse
-- answers "may I ask another question" — it cannot answer "which of these two prompts is the
-- expensive one", because by the time the day's total is interesting the two prompts are mixed
-- into it.
--
-- So the same number, kept where the comparison is: on the step of the run that spent it. Both
-- columns are on `run_step` and not on the card, for the reason 036 keeps the card's memory to one
-- result — a card is the shape and a run is one attempt at it, and the cost belongs to the attempt.
--
-- Zero means "not measured", which is every step run before this migration and every step done by
-- an agent rather than by a model call: the CLI reports a cost for a headless answer and this
-- console does not price an agent's work. That is said in words on the card rather than shown as
-- a suspiciously round zero.

ALTER TABLE run_step ADD COLUMN usd REAL    NOT NULL DEFAULT 0;
ALTER TABLE run_step ADD COLUMN ms  INTEGER NOT NULL DEFAULT 0;
