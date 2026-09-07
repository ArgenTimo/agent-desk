-- One undo for the workbench, and one for all of it.
--
-- "Сценарий 11 требует этого прямо («верни как было»), но нужно это везде: соединение карточек,
-- раскрытие проекта в сорок карточек, разложенный по колонкам верстак, сгенерированная схема.
-- Каждое из этого меняет поверхность целиком, и без отмены никто не станет пробовать. Одна отмена
-- на всё, а не своя у каждой фичи — иначе через полгода их будет восемь и все с разным поведением."
--
-- The second sentence is the design. Every one of those four already funnels through two writes —
-- the whole bench (040-bench.sql) and the lines between cards (034-card-ties.sql) — so there is
-- one place to record what the surface was, and undo needs to know nothing about what changed it.
-- A feature added next year is undoable without touching this, and cannot bring an eighth undo
-- with it.
--
-- ## What "the surface" is, and what it deliberately is not
--
-- Which cards are on the bench, where each one sits, and the lines drawn between them. That covers
-- all four of the examples above and nothing else claims to.
--
-- A card's **role**, its **fields** and what it is **allowed to do** are not here, and that is a
-- decision rather than an omission: they belong to the card, not to the surface, and they survive
-- a card being taken off and put back — which is a feature somebody uses. An undo that restored
-- them would take back a role somebody set an hour ago because a card moved a minute ago.
--
-- ## Why a blob
--
-- The whole surface, as JSON, in one row. A history of a thing whose only use is to be restored
-- whole is not a thing to normalise: querying *into* an old surface is not a question anybody has,
-- and the tables it would join to describe the present rather than that moment. `store/repo.py` is
-- already the module that parses this program's own JSON (tests/unit/test_structure.py names it),
-- so nothing moves to accommodate this.
--
-- ## Why it is bounded, and why the bound is small
--
-- A surface is written every time somebody drags a card, and each row is the whole of it. Fifty
-- steps back is more than anybody reaches for — past a handful, "undo until it looks right" stops
-- being a thing a person can aim, and the honest control for that is a saved workbench.

CREATE TABLE bench_was (
    at      INTEGER PRIMARY KEY AUTOINCREMENT,
    made_at INTEGER NOT NULL,
    surface TEXT NOT NULL
);
