-- A session that is not allowed to idle (docs/adr/0009).
--
-- Keyed by the session's short id, which is the name the CLI's own `stop`, `logs` and `attach`
-- take and the prefix of the full id `--resume` takes. Not by project: this switch is about one
-- conversation, and two sessions in the same repository are two decisions.
--
-- `resume_at` is what makes a limit a wait instead of a failure. When the CLI refuses because the
-- account has nothing left to spend, the switch stays on and this says when to look again — which
-- is the difference between a console that carries on after lunch and one that switched itself
-- off at the first refusal.
--
-- `failures` is the same two-in-a-row rule the other two loops use, and `disarmed_why` is the
-- sentence the card shows afterwards. A switch that turned itself off without saying why is a
-- switch somebody turns back on and watches fail again.

CREATE TABLE IF NOT EXISTS kicking (
    short_id     TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL DEFAULT '',
    cwd          TEXT NOT NULL DEFAULT '',
    armed_at     INTEGER,
    kicks        INTEGER NOT NULL DEFAULT 0,
    kicked_at    INTEGER,
    resume_at    INTEGER,
    failures     INTEGER NOT NULL DEFAULT 0,
    disarmed_why TEXT,
    per_hour     INTEGER NOT NULL DEFAULT 4
);
