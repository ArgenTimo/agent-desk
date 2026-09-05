-- An idea can hold other ideas.
--
-- Two things arrive as a group and neither is a list. A message that held several thoughts is one
-- thing somebody typed and several things they meant — the message is the parent and the thoughts
-- are under it, so a week later "what was I saying" still reads as one thought rather than as
-- three fragments in a row. And a human looking at the inbox sees that four separate ideas were
-- really one piece of work, and says so by dragging one onto another.
--
-- One level is not enforced here, and the console renders as deep as it finds. What it will not do
-- is make a loop: a parent that is its own descendant is refused at the point somebody asks for it
-- (docs/05-ideas.md).

ALTER TABLE idea ADD COLUMN parent_id TEXT REFERENCES idea(id);

CREATE INDEX idea_by_parent ON idea (parent_id);
