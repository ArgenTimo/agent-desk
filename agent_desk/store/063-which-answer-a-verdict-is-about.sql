-- Which answer a check's verdict is about.
--
-- Found by using it. "Из карантина растут исправленные ответы": pressing "try again" on a failed
-- check produces a new answer, and that answer is joined to the check — it was made out of it. So
-- the check then reached two answers, refused to choose between them, and could not be pressed
-- again. The gesture built the thing that stopped the gesture.
--
-- The quarantine had the same fault from the other side. It was derived from "what does this check
-- reach", which is the right answer to "what will it read next" and the wrong answer to "what did
-- it judge". Those are two questions and they part company the moment a second answer arrives.
--
-- So the verdict names its answer. The frame is drawn round *that*, whatever the lines say now, and
-- a check does not read again something it has already set aside — which leaves exactly one answer
-- to press it on, which is the corrected one.
--
-- Cleared with the verdict, by the same UPDATE: a card that remembers what it judged while saying
-- it has judged nothing is the pair of facts disagreeing.

ALTER TABLE check_card ADD COLUMN about TEXT NOT NULL DEFAULT '';
