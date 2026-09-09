-- One thing that was worked out about this project, and why it is true.
--
-- «Каждая сессия начинается с нуля и заново выясняет то же самое: почему здесь так, что уже
-- пробовали, что решили и почему. Ответы существуют — они в коммитах, в решениях, в головах, — но их
-- дешевле вывести заново, чем найти, и поэтому их выводят заново.»
--
-- The inbox already holds thoughts that cost no agent any context. The same trick works for what a
-- project is *like*: one fact, one reason, and a pointer to what settles it.
--
-- ## Why the reason is a column and not a convention
--
-- «Заметка без причины — это то, что следующий читатель отменит, не зная, что ломает.» A note
-- saying "the reader must check procStart" is a line somebody deletes while tidying. The same note
-- with "because pids are reused and a dead session then reads as busy" is one they leave alone. The
-- reason is half the record and the half that makes it worth keeping, so it is a column, and
-- `otherwise` is the sentence that says what breaks — the part a reader needs at the moment they
-- are about to do the other thing.
--
-- ## Why a source is required
--
-- «Источник обязателен: коммит, файл или имя человека — факт без источника не записывается.» A
-- fact nobody can chase is a rumour with a timestamp, and a store full of those is worse than an
-- empty one because it looks like knowledge. The check is in `record_known`, which is the one door
-- in: a NOT NULL column would accept an empty string, and an empty string is exactly the shape a
-- caller with nothing to cite would send.
--
-- ## Why the files are on the row
--
-- «Сто фактов в контексте не лучше нуля. Отдаётся то, что называет файлы, которых касается работа.»
-- The whole store is not an answer, and the useful narrowing is not by project — a project is
-- everything — but by what the work in front of somebody touches. So a fact names the files it is
-- about, one per line, and the reader asks for the ones that name these.
--
-- A fact that names no file is not an oversight: it is a fact about the project rather than about
-- a part of it, and it comes back to every reader.

CREATE TABLE known (
    id        TEXT PRIMARY KEY,
    what      TEXT NOT NULL,
    why       TEXT NOT NULL DEFAULT '',
    -- What happens to somebody who does it the other way. Empty where nobody said.
    otherwise TEXT NOT NULL DEFAULT '',
    -- A commit, a file, or a person's name. Never empty: `record_known` refuses.
    source    TEXT NOT NULL,
    -- The files this is about, one per line. Empty means it is about the project.
    files     TEXT NOT NULL DEFAULT '',
    at        INTEGER NOT NULL
);
