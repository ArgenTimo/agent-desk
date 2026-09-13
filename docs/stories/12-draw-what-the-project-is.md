# 12 · Draw what the project actually is

From the author:

> я хочу иметь возможность написать в запрос например что-то типа «нарисуй мне схему базы данных
> текущего проекта» или «создай мне матрицу фич и что они закрывают в текущем проекте» — в результате
> на верстаке я хочу видеть большое количество корректно связанных информативных блоков — не делай
> фичи именно под эти 2 примера, а реализуй гораздо гибче, функциональнее и масштабируемее.

## What was already there

A drawing branch exists and it already has a second vocabulary — things and named relations, not only
process steps — added so that «как у нас устроена БД» could be drawn at all
([`tests/unit/test_draw_anything.py`](../../tests/unit/test_draw_anything.py)). It also refuses to draw
from memory: a model may answer `cannot: <what it would need to be shown>` instead of a plausible
picture of something that does not exist.

## Why neither example works today

**The model cannot see the project.** The drawing is asked with the words in the field and the cards
on the bench, and nothing else. "The current project" is not in front of it, so the honest answer is
`cannot:` — which is the refusal working as designed, and the reason the feature does nothing.

**A thing is a name and two lines.** Drawn things become step cards with the role `object` and one
`what` field. A table with its columns, a feature with what it covers, a service with its endpoints —
none of those fit. The result is a handful of labels, not "informative blocks".

**The classifier thinks drawing is only for processes.** Its description of `draw` is "a sequence of
steps with decisions in it", so a request for a schema or a matrix is as likely to be answered in
prose.

**Forty cards arrive stacked.** Every drawn card is placed under the answer and gets its own `wrote`
line from it, which is a fan of forty lines hiding the relations the drawing is for.

---

## 1 · The drawing reads the project it is about

> As someone who chose a project, I want "draw the schema of the current project" to be drawn from its
> files, not from what a model remembers databases look like.

**Done when** the drawing is run with read-only access to the addressed project's checkout — the
chosen project's, the bench's, or this console's own — and told where it is; and a project with no
checkout on this machine gets a sentence saying so instead of a drawing.

## 2 · A thing on the bench carries what it is

> As someone looking at the drawing, I want each block to say what kind of thing it is and its
> details — the columns, the endpoints, what a feature covers — without opening it.

**Done when** a drawn thing is a card of its own kind with a short kind word, a title and a list of
lines, shown on the card; and the lines between them carry their relation's name.

## 3 · Any map, not two

> As someone asking for a schema today and a dependency map tomorrow, I want the same request shape to
> work for both without anybody writing a feature for each.

**Done when** the vocabulary is general — any kind word, any relation name — and nothing in the code
names "database" or "feature matrix"; the classifier treats "draw / map / visualise what exists" as a
drawing.

## 4 · A big drawing is readable

> As someone who asked for sixty blocks, I want sixty blocks laid out by how they relate, not a column
> of cards with sixty lines to the answer.

**Done when** a map's cards are laid out as a graph on arrival, are joined to the answer once, and a
drawing bigger than the bound says how much it left out.

---

## What was deliberately not asked for

**Writing into the project.** Reading a checkout is allowed; writing into one is the second of the
five rules. The drawing run is read-only.

**Keeping the drawing in sync with the code.** A drawing is a picture of the project when it was asked
for, marked with where it came from. Redrawing is asking again.
