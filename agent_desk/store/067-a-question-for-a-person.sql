-- A question an agent left for a person, and the answer it comes back for.
--
-- ## Why this is 067 and not 066
--
-- 066 is burned. The author's database records it applied, with no table to show for it and no file
-- in any commit — a migration that existed on disk for an afternoon and was never committed. Nobody
-- else's database has it, and reusing the number would mean this file silently never runs on the
-- one machine that matters. Forward-only means going round a number, never reusing one
-- (docs/adr/0003).
--
-- «Агент, упёршийся в решение, которое не его, сегодня умеет одно — остановиться и ждать. Всё, что
-- он сделал до вопроса, стоит в очереди за ответом.»
--
-- The console is the only place a question can wait for somebody without occupying anybody's
-- window. The agent leaves it here, goes on with what does not depend on the answer, and comes back
-- for it later.
--
-- ## Why this does not break adr/0002
--
-- Nothing is written into a running session's context. The row is written by the asker, read by the
-- asker, and the only thing a person does is press one of the options — which is the human click
-- that document requires, arriving on the other side of the exchange from the one it was written
-- about.
--
-- ## Why the options are a column and not a table
--
-- A question with options is a question somebody answers by pressing, and pressing is why the
-- options are enumerated at all: «человек отвечает нажатием, а не набором текста». They are one per
-- line, they are never queried, and the whole of what anything does with them is show them as
-- buttons. A table of them would be a join to render a list this program never asks a question of.
--
-- ## `done` is what is already built and waiting on this
--
-- The card has to show what is on hold, or it is a question with no cost attached and it waits
-- behind everything that has one. It is the asker's own sentence, because nothing here can see the
-- inside of the work that stopped.
--
-- ## An unanswered row is a blocker, and this is the first one that is a fact
--
-- `agent_desk/web/blockers.py` refused "waiting on a person" because it was an inference from
-- somebody else's silence. This one is not: an agent said, in writing, that it is waiting, and it
-- said what for. It is the same kind of fact as a task this console started and watched fail.

CREATE TABLE asked (
    id          TEXT PRIMARY KEY,
    question    TEXT NOT NULL,
    -- One option per line. Empty means the asker offered none, which is a question a person
    -- answers in their own words rather than by pressing.
    options     TEXT NOT NULL DEFAULT '',
    -- What is already done and waiting on the answer, in the asker's words.
    done        TEXT NOT NULL DEFAULT '',
    -- Who is asking, in whatever name they gave. Not authenticated and not treated as if it were:
    -- it is on the card so a person knows whose work they are unblocking.
    who         TEXT NOT NULL DEFAULT '',
    at          INTEGER NOT NULL,
    -- NULL until somebody presses. Distinct from '' so that an answer somebody deliberately left
    -- blank is not the same row as one nobody has looked at.
    answer      TEXT,
    answered_at INTEGER
);

CREATE INDEX asked_unanswered ON asked (answered_at);
