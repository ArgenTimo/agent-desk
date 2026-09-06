-- What a link to another service is, as opposed to only where it points.
--
-- A project's links have always been a list of places it also lives. What the list could not say
-- is the thing somebody most needs to know: which of these this console can actually *do*
-- something with. A Jira link with a credential is a board it reads and files into; a GitHub link
-- is a link. They rendered identically, which is how five connectors become five things nobody
-- can predict the behaviour of.
--
-- Nullable, and read through `agent_desk/connectors.py` rather than trusted raw: every row that
-- existed before this column did has none, and guessing one from the URL at read time is both
-- correct for those rows and one less migration to get wrong.

ALTER TABLE project_link ADD COLUMN kind TEXT;
