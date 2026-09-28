# 14 — A control that works wherever it was drawn

«Кнопка choose не активна в проектах, буквально не кликабельна.» It was clickable once: the board
is written with `innerHTML`, and markup written that way is invisible to htmx until it is handed
to it. Fixed for the board in 974a306. Counting the live page afterwards found the same thing on
the workbench: 110 htmx controls inside card bodies, 26 of them dead — every idea card's project
picker, fetched from `/cards/idea` and never processed.

## Stories

1. **As somebody working on the bench**, I want the project picker on an idea card to post like it
   says it does, so that moving an idea to a project does not navigate the whole console away.
2. **As somebody who re-parents an idea by dragging it**, I want the idea column that comes back to
   work as well as the one the page was served with, so that the second drag is not a dead one.
3. **As somebody reading a checked card**, I want the controls on the card a check re-reads to
   work, so that a verdict does not quietly break the card it was written on.
4. **As the next person to add a swap to console.js**, I want a test that fails when server markup
   is written into the page and never handed to htmx, so that the class is caught and not one case.

## Ideas

- Every place console.js writes server-rendered markup with `innerHTML` hands it to htmx after —
  the card body, a re-read check, the idea column after a drag, a session's tail (stories 1–3).
- A test over console.js that finds every such write and fails when no `htmx.process` follows it;
  the one exemption is the poster that exists only when htmx is absent (story 4).
