-- When a deferred idea comes back, and what has to be true for it to come back.
--
-- "Отложенная задача должна иметь момент срабатывания: либо вычисленный («когда освободится»,
-- «после того как пройдёт гейт»), либо названный («напомни завтра») — и в этот момент срабатывать
-- сама."
--
-- Before this, deferring was not a state: a thing put off stayed in the pool as a thought among
-- other thoughts, and the difference between "later" and "never" was whether somebody happened to
-- scroll past it. A deferred task with no moment is a task nobody started.
--
-- Two columns because there are two kinds of moment and they answer different questions.
--
-- `wakes_at` is a named one — "напомни завтра" — stored as an epoch second. It is a clock, and a
-- clock needs nothing to be true except that time passed.
--
-- `wakes_when` is a computed one — "когда освободится", "после того как пройдёт гейт" — stored as
-- the *name* of a condition this program knows how to check, never as free text. A condition
-- nobody can evaluate is a moment that never arrives, and a column that accepts any sentence
-- would fill up with exactly those. agent_desk/ideas/waking.py holds the list, and anything it
-- does not recognise is refused at the point somebody types it rather than stored and forgotten.
--
-- Both may be set: "tomorrow, once the gate is green" is one moment with two halves, and it fires
-- when both are true. Neither set is the ordinary case — an idea in the pool, not deferred.
--
-- `woke_at` is the record that it fired. It exists so that a moment fires once: a condition like
-- "nothing is running" is true for as long as nothing is running, and without this the same idea
-- would be started every time the loop came round.

ALTER TABLE idea ADD COLUMN wakes_at INTEGER;
ALTER TABLE idea ADD COLUMN wakes_when TEXT;
ALTER TABLE idea ADD COLUMN woke_at INTEGER;
