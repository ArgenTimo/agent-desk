# 13 — A drawing that is not silent

Observed on the real engine: «нарисуй схему базы данных текущего проекта» read this repository
for three minutes and spent $1.24. Every one of those minutes showed only a blinking caret, and the
finished block never said what it cost.

## Stories

1. **As the person who asked for a map**, I want to see which file it is reading right now, so that
   three minutes of reading is not indistinguishable from a console that has stopped.
2. **As the person who pays for the day**, I want the finished drawing to say what it cost, so that
   I can decide whether to ask for the whole project again or only a part of it.
3. **As the person who asked**, I want the "reading…" line gone once the cards are drawn, so that a
   finished block does not still claim to be working.
4. **As a reviewer of the security rules**, I want the path shown while it reads to be scrubbed like
   an ordinary answer's, so that a second output path does not skip redaction (docs/07-security.md).

## Ideas

- `_map_it` passes `on_step` into the run and writes the step to `DOING`, scrubbed; clears it on
  every exit (stories 1, 3, 4).
- `_map_it` collects `on_cost`, and the drawn sentence ends with what the reading cost when it was
  measured; zero is "not measured" and is not said (story 2).
