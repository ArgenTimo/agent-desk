-- What a run was started with, in the words somebody typed.
--
-- "Весь запуск и ввод происходит из одного места, с поля ввода. То есть пайплайн получает вход не
-- из формы внутри карточки, а из того, что человек написал внизу — и это же поле его запускает."
--
-- A pipeline is a shape that is run more than once with different inputs — that is what makes it
-- worth building rather than asking the question twice — and the input therefore belongs to the
-- *run*, not to a card. A field inside a step would be the input of one step of one shape, edited
-- in place, and comparing two runs of it would be comparing a thing with itself.
--
-- Empty for every run started before this and for every run of a process that needs no input,
-- which is most of the drawings this console has executed so far.

ALTER TABLE run ADD COLUMN given TEXT NOT NULL DEFAULT '';
