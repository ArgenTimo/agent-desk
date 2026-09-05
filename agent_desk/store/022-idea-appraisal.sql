-- What a background pass thinks about an idea, kept apart from what a person thinks.
--
-- Three columns and every one is nullable, because "nobody has looked at this yet" is a real
-- state and the alternative — a default that reads like a judgement — is the guessed status
-- CLAUDE.md's fifth rule is about.
--
-- `size` and `shape` are a *model's* reading of the text, and the console renders them as that:
-- a colour and a word, never a filter that hides anything and never a state a person did not set.
-- `state` stays the human's column and this pass never writes it.
--
-- `appraised_at` is what stops the pass re-reading sixty ideas every thirty seconds: an idea is
-- looked at once, and again only if somebody rewrites it.

ALTER TABLE idea ADD COLUMN size TEXT;
ALTER TABLE idea ADD COLUMN shape TEXT;
ALTER TABLE idea ADD COLUMN appraised_at INTEGER;
