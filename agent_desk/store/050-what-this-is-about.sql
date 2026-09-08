-- The card an enquiry starts from.
--
-- "Создаётся карточка начала, например — описание проекта."
--
-- A question relates to something, and the first one relates to nothing that has been said yet.
-- Without a card to start from, the only thing a first question can hang off is the question
-- before it — which is a feed, and a feed is what scenario 9 is trying to stop being. So the root
-- is a thing of its own: not a question and not an answer, but what all of it is about.
--
-- ## Why this is not a column on bench_card
--
-- "Which card is the beginning" is a fact about the *enquiry*, not about the card. The same card
-- can sit on two benches (046) and be the beginning of neither, one or both of them, and a column
-- on the card would have to say all three. It would also leave "one beginning per chat" as a rule
-- somebody remembers rather than something the database can refuse: here it is the primary key.
--
-- ## Why the name is not a foreign key
--
-- A beginning outlives the arrangement it was made in. Take the card off the bench and put it back
-- and it is the same card by name, but the row in `bench_card` is a new one — a foreign key would
-- have deleted the beginning halfway through a rearrangement nobody thought was destructive. A
-- name that matches nothing on the bench marks nothing and says nothing, which is the correct
-- behaviour and needs no cleanup.

CREATE TABLE began (
    thread_id TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    at        INTEGER NOT NULL
);
