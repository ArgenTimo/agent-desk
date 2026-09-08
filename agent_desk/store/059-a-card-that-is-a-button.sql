-- A card that holds a request and sends it when pressed.
--
-- "Карточка-кнопка с тонкими настройками. По умолчанию при нажатии просто отправляет указанный в
-- ней запрос, как будто бы мы его вписали в поле ввода, только без создания карточки запроса…
-- Кнопок можно создавать любое количество."
--
-- The value is not that it saves typing. It is that a request somebody makes twenty times a day —
-- "скомбинируй выбранные идеи", "декомпозируй" — stops being something they retype and starts being
-- something on the surface, next to the things it acts on. What it acts on is the other half:
--
--   "Если кнопка ни к чему не подключена связью — она работает со всем, что выделено; если
--    подключена к чему-то — работает с тем, с чем подключена."
--
-- That rule turns a line on the workbench into scope. Everywhere else here a line is a statement
-- about two cards; from a button it decides what the press reaches, which is the first time the
-- drawing does something rather than describing something.
--
-- ## Its own table, and not a step card
--
-- `step_card` is the card you draw before the thing exists, and its meaning comes from a role out
-- of the five. A button is not a step in a process: the run engine must never try to execute one,
-- and giving it a role is how that would happen. Its kind is unknown to `roles.NATURALLY`, so it is
-- an Object — a thing that exists — and `process.STEPS` does not have it.
--
-- ## A block a button sent
--
-- `by_button` on the block, because the workbench draws a card for every question in the thread and
-- a button is explicitly "как будто бы мы его вписали в поле ввода, только без создания карточки
-- запроса". The answer still becomes a card; the question does not.

CREATE TABLE button_card (
    id      TEXT PRIMARY KEY,
    label   TEXT NOT NULL,
    prompt  TEXT NOT NULL DEFAULT '',
    made_at INTEGER NOT NULL
);

ALTER TABLE block ADD COLUMN by_button INTEGER NOT NULL DEFAULT 0;
