-- What a person said a line really was, and how a prompt scored against a set of those.
--
-- «За эту смену я трижды правил `classify.kind_prompt` — восемьдесят строк инструкций, которые
-- решают, поднимется ли агент в воркдире. Проверить, стало ли лучше, было нечем: тесты утверждают
-- ТЕКСТ промпта, а не его поведение.»
--
-- A test that asserts a prompt contains a sentence proves the sentence is there. It says nothing
-- about whether the prompt still decides correctly, which is the only thing the prompt is for.
--
-- ## The set is this console's own history
--
-- «В базе уже лежат сотни блоков с тем, что человек напечатал, и с тем, каким видом консоль это
-- сочла. Не хватает второй колонки — что это было на самом деле.» So `labelled` holds one column:
-- what a person says the line really was, kept apart from what the classifier decided, because a
-- measurement that read the classifier's own answer as the truth would measure nothing.
--
-- Some of it is already there for free: a block whose thread a human set, or whose kind a human
-- corrected, is a person having already said what it was. Those are labels nobody has to type
-- again, and `agent_desk/grading.py` reads them.
--
-- ## `graded` is why any of this exists
--
-- «Прогон без истории — это одно число. Прогон, привязанный к коммиту, — это ответ на вопрос "моя
-- правка промпта улучшила его или нет".» A score with no commit beside it cannot answer the only
-- question anybody runs it for. `right` and `of` rather than a percentage: 41 of 50 and 82% are the
-- same number until the set changes size, and then only one of them is still comparable.

CREATE TABLE labelled (
    block_id TEXT PRIMARY KEY REFERENCES block(id),
    -- What it really was, in the same vocabulary the classifier answers in (`BlockKind`).
    kind     TEXT NOT NULL,
    at       INTEGER NOT NULL
);

CREATE TABLE graded (
    id     TEXT PRIMARY KEY,
    at     INTEGER NOT NULL,
    -- The commit the prompt was at. Empty where nothing could be read — a working tree with no git
    -- in it — and that is said rather than filled in with a guess.
    commit_sha TEXT NOT NULL DEFAULT '',
    -- Which reader was measured: 'kind' today, and the others when their sets exist.
    what   TEXT NOT NULL,
    right_ INTEGER NOT NULL,
    of     INTEGER NOT NULL
);

CREATE INDEX graded_by_what ON graded (what, at);
