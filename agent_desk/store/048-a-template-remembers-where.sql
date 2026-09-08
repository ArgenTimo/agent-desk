-- A saved drawing remembers where its cards were, not only what shape they made.
--
-- "Использованный шаблон высыпает карточки кучей, и каждый раз их раскладывают заново. Позиции —
-- часть того, что человек собрал, и терять их не нужно."
--
-- 038 saved a template as a *shape* — the roles, what each step says, what each may do, and the
-- lines between them — and that argument still holds for everything it covers: a template makes
-- new cards, so it cannot save the ones it was drawn from. But where those cards sat is not a fact
-- about the cards. It is a fact about the drawing, and it was arranged by hand, which is exactly
-- the kind of work 042 exists to stop the console throwing away.
--
-- So the offsets travel with the step. Offsets rather than coordinates: a template used on a bench
-- that already has cards on it must not drop its own on top of them, and a drawing whose shape
-- survives being placed anywhere is a drawing rather than a screenshot. The left-most and top-most
-- card of the saved set is the origin, so `dx`/`dy` are the drawing's own geometry and the console
-- decides where to put the whole of it.
--
-- Nullable, because every template saved before this has no answer and inventing one would put
-- somebody's older drawing in a grid it never had. Absent means "lay it out the way you always
-- did", which is what those templates already do.

ALTER TABLE template_step ADD COLUMN dx INTEGER;
ALTER TABLE template_step ADD COLUMN dy INTEGER;
