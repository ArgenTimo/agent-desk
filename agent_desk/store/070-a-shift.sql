-- A stretch of work, and the things that happened during it.
--
-- «Эта сессия сжималась дважды. Каждый раз я терял детали и заново выяснял, где нахожусь:
-- перечитывал пул, идею, код.»
--
-- Everything needed to answer "where was I" is already in this database — which idea was closed by
-- which commit, which runs went, what was spent. What is missing is one thread with time on it, so
-- that the answer costs five hundred tokens instead of twenty thousand.
--
-- ## Written as it happens, not assembled at the end
--
-- A summary written at the end is a summary that is never written, because the end is exactly the
-- moment a context window runs out. Each line is written by whatever did the thing: closing an
-- idea writes one, recording a commit writes one, a gate result writes one.
--
-- ## No button
--
-- «Смена начинается сама с первой записи и закрывается по бездействию — не кнопкой.» A shift that
-- has to be started is a shift somebody forgets to start, and the first thing they want from it is
-- the part that happened before they remembered. So the first line opens one, and a gap longer
-- than `Store.SHIFT_ENDS_AFTER` closes it: the next line after a long silence belongs to a new
-- stretch of work, and pretending otherwise would make one shift the whole week.
--
-- `ended_at` is therefore written when the *next* shift opens rather than when this one stops —
-- nothing is watching a clock, and a program that needed a timer to close a row would lose the row
-- every time it was restarted.
--
-- ## `what` is a closed vocabulary
--
-- 'idea', 'commit', 'gate', 'run', 'note'. Five words, so that reading a shift back is reading a
-- table rather than parsing sentences, and so that a sixth kind of line is a decision somebody
-- makes rather than a string somebody passes.

CREATE TABLE shift (
    id        TEXT PRIMARY KEY,
    began_at  INTEGER NOT NULL,
    -- NULL while this is the one being written to.
    ended_at  INTEGER,
    -- What it was about, in the words of whatever opened it: usually the first thing that happened.
    note      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE shift_step (
    id       TEXT PRIMARY KEY,
    shift_id TEXT NOT NULL REFERENCES shift(id),
    at       INTEGER NOT NULL,
    -- idea | commit | gate | run | note
    what     TEXT NOT NULL,
    said     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX shift_step_by_shift ON shift_step (shift_id, at);
