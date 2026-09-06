-- What a card *is* in a process, as opposed to where it came from.
--
-- From the first user's feedback: "нам нужно несколько типов карточек на доске (верстаке) —
-- Object (что-то существует), Action (что-то сделать), Decision (выбрать / проверить условие),
-- Event (что-то произошло), Result (что-то получилось)… карточка может менять тип по ходу
-- процесса."
--
-- That last clause is the whole reason this is a table and not a column on anything. A card's
-- `kind` — session, idea, blocker, folder — says where it is read from, and it cannot change: an
-- idea does not become a session. Its *role* is what it is doing in the process somebody is
-- describing, and it changes as the description changes. One field cannot be both, and the
-- version of this that reused `kind` would have made "this idea is the Result of that step"
-- unsayable.
--
-- Keyed by card name (`kind:id`), the same string the workbench, the ties and the layout already
-- use, so a role can be given to anything that can be put on the bench without every kind of card
-- needing a column of its own.
--
-- Absent is a real answer and the common one: a card nobody has typed has the role its kind
-- suggests (agent_desk/roles.py), and a row here is somebody having said otherwise.

CREATE TABLE card_role (
    name    TEXT PRIMARY KEY,
    role    TEXT NOT NULL,
    set_at  INTEGER NOT NULL
);
