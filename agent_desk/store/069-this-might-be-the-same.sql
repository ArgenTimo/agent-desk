-- A suggestion that two ideas are one, waiting for somebody to say.
--
-- «Ответ — предложение с кнопками, а не автоматическое связывание.»
--
-- `agent_desk/ideas/kin.py` has been asking a model whether a new thought repeats one already in
-- the pool since the pool existed, and acting on the answer: `under N` hung the new idea under the
-- old one there and then. That was defended on the ground that nothing was lost — both wordings
-- stay readable and a wrong link can be dragged back out — and the defence is true. It is still the
-- wrong shape. A list that quietly reorganises itself between the moment somebody writes a thought
-- and the moment they look at it is a list they stop trusting to hold what they put in it, and the
-- cost of being wrong is paid by the person who has to notice.
--
-- So the judgement becomes a row here, and a person presses. Both answers are recorded, because
-- "these two are different" is a fact worth keeping: without it the same pair is offered again
-- every time the pool is re-read, and a suggestion that comes back after being refused is noise
-- with a memory problem.
--
-- ## Why the pair is stored and not recomputed
--
-- Recomputing means asking a model, which costs money and takes seconds, and it means the same
-- question can get two different answers on two page loads. A suggestion somebody is looking at
-- must not change while they read it.
--
-- ## `kind` is what the model said, and it is not what happens
--
-- `same` and `under` are two different sentences to a reader — "you already wrote this" against
-- "this is part of that" — and one action: the idea is hung under the other. Nothing here ever
-- writes `idea.text` (docs/05-ideas.md), so folding two wordings into one is not among the things
-- that can happen.

CREATE TABLE looks_like (
    id        TEXT PRIMARY KEY,
    idea_id   TEXT NOT NULL REFERENCES idea(id),
    like_id   TEXT NOT NULL REFERENCES idea(id),
    -- 'same' or 'under', as the model answered.
    kind      TEXT NOT NULL,
    at        INTEGER NOT NULL,
    -- NULL while nobody has pressed. 'joined' or 'apart' once somebody has.
    took      TEXT,
    settled_at INTEGER
);

-- One suggestion per pair. Asking again about a pair somebody has already answered is the noise
-- this table exists to prevent.
CREATE UNIQUE INDEX looks_like_pair ON looks_like (idea_id, like_id);
