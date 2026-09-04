-- What one call to the model was actually built from, in the words the console used.
--
-- Every question carries exactly what was put in front of it — the cards in the output field, and
-- whichever earlier answers were attached (docs/04-threads-and-blocks.md). A block that cannot
-- say what it carried is a block whose answer cannot be explained afterwards: "why did it say
-- that" is a question about the context, and the context was a decision somebody made in a second
-- and has already forgotten.
--
-- One line per thing carried, newline-separated, generated at submission and never edited. It is
-- a description rather than the content: the content is the sessions and the blocks, which are
-- read fresh and stored once already.

ALTER TABLE block ADD COLUMN context TEXT;
