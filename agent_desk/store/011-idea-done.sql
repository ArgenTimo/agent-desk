-- A fifth state for an idea: it was built.
--
-- ../docs/05-ideas.md said there were exactly four — new, kept, promoted, dropped — and the reason
-- was that priorities and assignees turn a notebook into a backlog nobody maintains. This is not
-- that: `done` is the one thing the other four cannot say, and without it the inbox fills with
-- thoughts that were acted on months ago and reads as a list of things nobody did.
--
-- `dropped` was the nearest word and it is the wrong one. "We decided not to" and "it is in the
-- product" are different answers to "what happened to my idea", and a notebook that cannot tell
-- them apart is answering neither.
--
-- Nothing here sets it automatically from a guess: an agent finishing a task marks the ideas that
-- task was dispatched *for*, and a human can put any of them back with Keep.

ALTER TABLE idea ADD COLUMN done_at INTEGER;
