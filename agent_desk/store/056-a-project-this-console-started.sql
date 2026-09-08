-- The repository a message pointed at, kept on the block that carried it.
--
-- "Я просто условно кидаю в ввод ссылку на пустой реп… прошу сделать прототип на основе… целый
-- проект (с его отслеживанием и прочим)."
--
-- `agent_desk/pasted.py` already reads a message into its parts and writes what it found into the
-- block's context, which is a list of sentences for somebody to read. This is the same fact in the
-- one shape a control can act on: the address, on the block, so the offer to start a project from
-- it is a button rather than a template picking a URL back out of a paragraph.
--
-- ## Why the offer and not the act
--
-- Cloning a repository and queueing work in it is a side effect nobody asked for by typing. Two
-- acts, and the second is a click — the same rule that keeps a message to a session behind a
-- button (docs/adr/0002) and a ticket from starting itself (docs/adr/0007). The column is what
-- makes the offer possible; pressing it is what makes it happen.

ALTER TABLE block ADD COLUMN from_repo TEXT NOT NULL DEFAULT '';
