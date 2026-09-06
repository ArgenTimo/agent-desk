-- Whether a chat's name was written by this program or typed by a person.
--
-- A chat takes the first thing said in it as its name, which is right most of the time and wrong
-- for exactly the case the pool named: one that opened with a greeting and became a week of work
-- on the parser is still called after the greeting. So the name is rewritten once the chat is
-- actually about something.
--
-- What this column does today: **it is rewritten once**, so a long conversation is not renamed on
-- every message — that would make the tab bar move under somebody's hand while they were reading
-- it.
--
-- What it is also *for*, when the time comes: there is no way to rename a chat by hand yet, so
-- every name here was chosen by this program. The day a rename field appears, this is the flag
-- that separates the two — a name a person typed is somebody saying what this is, and a model does
-- not get to disagree with it.

ALTER TABLE thread ADD COLUMN renamed_at INTEGER;
