-- A card with behaviour in it, kept under a name and put on any workbench.
--
-- "Отдельная крупная фитча — конструктор инструментов. Уникальная карточка, в которую можно
-- закладывать разнообразный функционал: например заложить туда кнопку с промптом… Хранятся в
-- списке под проектами, слева снизу."
--
-- Two card kinds already hold behaviour rather than information: a button holds a request and sends
-- it when pressed (059), and a check holds a condition and decides (062). Both are made on one
-- workbench and die with it — somebody who writes "декомпозируй" as a button writes it again in the
-- next chat, and by the fourth chat they stop bothering. A tool is that card, kept.
--
-- ## Why this is not "save the card"
--
-- A card is a row plus where it sits plus what it is joined to. What is worth keeping is none of
-- those: it is the *behaviour* — the kind and the sentence. So a tool holds those two and putting
-- one on a bench makes a **new** card from them, which is why the same tool can be on four benches
-- at once with four different sets of lines. The same argument `038-steps-and-templates.sql` makes
-- about a saved drawing, and for the same reason.
--
-- ## Why the name is the key
--
-- One "декомпозируй" per console, because two of them is a list where somebody has to remember
-- which is the good one. Saving over an existing name replaces it, which is how somebody fixes a
-- prompt they got slightly wrong — and the tool on a bench is a separate card that keeps working
-- as it was, because it is a copy rather than a reference.

CREATE TABLE tool (
    name    TEXT PRIMARY KEY,
    -- Which kind of card this makes: the vocabulary is the card kinds that hold behaviour, and
    -- there are two of them. A third would arrive with the card kind it belongs to.
    kind    TEXT NOT NULL,
    -- What the card is made with: a button's request, a check's condition.
    said    TEXT NOT NULL DEFAULT '',
    made_at INTEGER NOT NULL
);
