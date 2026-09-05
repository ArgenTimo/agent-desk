-- Which project an idea is about.
--
-- An idea arrives with the board around it, and until now that context was a description — the
-- project's *name*, as it happened to be called when the thought was had. That is right for
-- remembering where you were and useless for deciding where the work goes.
--
-- So: the repository key, editable, and defaulting to this console's own project when nothing
-- says otherwise. A thought typed with no cards on the workbench is a thought about the thing in
-- front of you, and the thing in front of you is the desk (docs/05-ideas.md).

ALTER TABLE idea ADD COLUMN project_key TEXT;

CREATE INDEX idea_by_project ON idea (project_key);
