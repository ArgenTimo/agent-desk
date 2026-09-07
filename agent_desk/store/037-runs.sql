-- A drawing being run, and where it has got to.
--
-- The last piece of "под капотом контекст + агент + тулзы + пермишены + память + конкретное
-- выполнение по порядку, то есть движок". Everything before this described a process; this is the
-- record of one actually happening.
--
-- ## Why the bench is frozen into the run
--
-- `cards` holds the card names the run was started with, as one string, because what somebody has
-- on their workbench is a fact about a browser and it changes while a run is going. A run that
-- re-read the bench on every tick would change what it is doing because somebody dragged a card
-- off in another tab. The drawing at the moment somebody pressed run is the drawing that runs.
--
-- The lines and the fields are *not* frozen, deliberately. They live in this database, they are
-- what a step is told, and somebody correcting the wording of a step that has not started yet
-- should see that correction used. What must not move under a run is which cards are in it.
--
-- ## Why a step row rather than a column on the run
--
-- A run holds where it is (`at`), and `run_step` holds what happened at every step it has been
-- through — including what each one produced, which is the memory the next step is told about
-- (agent_desk/process.py). A run with one "current step" column and nothing else would have no
-- way to answer "what did step two produce", which is the whole of why the sequence is a
-- sequence.
--
-- `task_id` is the queued task doing the work, where there is one. There is not always one: a
-- read-only step is answered by asking rather than by starting an agent, and an Event is a step
-- that waits.

CREATE TABLE run (
    id          TEXT PRIMARY KEY,
    cards       TEXT NOT NULL,
    repo_key    TEXT NOT NULL,
    cwd         TEXT NOT NULL,
    at          TEXT NOT NULL DEFAULT '',
    started_at  INTEGER NOT NULL,
    finished_at INTEGER,
    stopped_why TEXT
);

CREATE TABLE run_step (
    run_id   TEXT NOT NULL,
    name     TEXT NOT NULL,
    task_id  TEXT,
    state    TEXT NOT NULL,
    made     TEXT NOT NULL DEFAULT '',
    detail   TEXT NOT NULL DEFAULT '',
    at       INTEGER NOT NULL,
    PRIMARY KEY (run_id, name)
);

CREATE INDEX run_step_run ON run_step (run_id);
