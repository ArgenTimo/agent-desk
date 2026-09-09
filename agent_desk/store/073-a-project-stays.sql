-- A project this console has seen stays on the board until somebody takes it off.
--
-- «Проекты, которые были добавлены в нашу систему, остаются висеть в ней до тех пор, пока мы их не
-- удалим отсюда. Даже если в проекте в конкретный момент нет ни одной ллм сессии.»
--
-- The board is built from the session registry, which is a picture of *right now*. A project whose
-- last session ended disappeared from it — and everything attached to that project stayed in the
-- database with nowhere to be seen: its ideas, its queue, its links, its subscription. A person who
-- closed a terminal lost the place they had been dragging cards into.
--
-- ## Why a row and not a derivation
--
-- Every other level of the board is derived: sessions belong to a directory, directories to a
-- repository, repositories to a project unless somebody said otherwise, and nothing is declared
-- that can be derived. This one cannot be. "This console has seen this project" is a fact about the
-- past, and the past is exactly what a reading of the present cannot recover.
--
-- ## Written when it is seen, and never on a schedule
--
-- The board is read every couple of seconds, and this is written from that read. `last_at` moves,
-- so a project's row says when it was last actually running, which is what somebody deciding
-- whether to take it off wants to know.
--
-- ## Taking one off is a person's, and it removes nothing else
--
-- Deleting this row makes the board stop showing a project that has no sessions. It does not touch
-- an idea, a task, a link or a subscription — those belong to the project rather than to the board,
-- and a control that quietly deleted them would be a delete button wearing "hide" as a label.

CREATE TABLE project_seen (
    repo_key TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    -- A checkout it was last seen in, so a card dragged onto it still has somewhere to run. Empty
    -- where none was known.
    cwd      TEXT NOT NULL DEFAULT '',
    first_at INTEGER NOT NULL,
    last_at  INTEGER NOT NULL
);
