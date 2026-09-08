-- Files a person has explicitly said may be opened.
--
-- "«Собери из них» означает, что файлы будут прочитаны — значит, это отдельное разрешение, которое
-- человек даёт явно, а не побочный эффект просьбы."
--
-- A folder on the workbench is a link and nothing in it is opened: names, kinds and sizes are all
-- `observe/folder.py` reads, and that rule is the whole reason it is safe to drop a directory that
-- may hold anything onto this bench. Making something *out of* those files needs their contents,
-- which is a different act and gets a different answer: one click per file, recorded here.
--
-- ## Why a row and not a flag on the card
--
-- Because the permission is about the file, not about the card. The same file can be dropped
-- twice, on two benches, in two chats; the person said "this file may be read" once, and they
-- said it about the file. And a row is what makes it answerable later: "which files has this
-- console been allowed to open" is a question with a list for an answer.
--
-- ## What a click cannot do
--
-- It cannot reach a credential. `~/.claude/.credentials.json`, `~/.claude/sessions/*.key` and any
-- `.env` are refused by the reader whether or not a row exists here — that rule is not a default
-- somebody may override, it is the third of the five in CLAUDE.md, and a permission table that
-- could unlock it would be the mechanism for breaking it. A row for such a path is never written.

CREATE TABLE readable (
    path TEXT PRIMARY KEY,
    at   INTEGER NOT NULL
);
