-- What a card says about itself, in the fields its role asks for (agent_desk/roles.py).
--
-- "Набор маленький и фиксированный на тип: поле, которое можно назвать как угодно, — это снова
-- свободный текст, а свободный текст движок исполнить не может."
--
-- So the *names* are not stored. `field` holds one of a fixed handful per role, checked before it
-- is written; a row whose name is not one of them cannot be created through the route, and one
-- left behind by a field that has since been removed is simply not rendered. Storing arbitrary
-- names here would have made this a notes table with a key on it, which is the thing the
-- feedback was explicitly against.
--
-- Keyed by card name and field, the same `kind:id` the roles and the ties use, so any card can
-- answer any of its role's questions without a column existing anywhere for it.
--
-- Kept when the role changes, deliberately. A card that was an Action and became a Result, then
-- back, should not have lost what somebody typed into it — "карточка может менять тип по ходу
-- процесса", and losing the words on every change would make that expensive rather than free.
-- Fields of a role the card no longer has are invisible, not deleted.

CREATE TABLE card_field (
    name    TEXT NOT NULL,
    field   TEXT NOT NULL,
    value   TEXT NOT NULL,
    set_at  INTEGER NOT NULL,
    PRIMARY KEY (name, field)
);
