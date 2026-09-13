# 11 · The project being worked on

From the author, in their words:

> блокеры отображаются общие для всех проектов — собираются из jira или из сессий. Идеи же
> отображаются только для конкретных проектов, то есть у проектов должна быть кнопка выбрать. При
> выборе проекта мы видим его идеи, но он не помещается на верстак. Если проект выбран, то по
> умолчанию запросы адресованы именно ему, если не выбран и нет другого контекста на верстаке —
> agent-desk — тот, кому адресованы запросы.

## What was already there, and where it disagreed

A choice of project existed — `/projects/focus`, "Show only this one" — three levels down, inside the
`⋯` menu of a project card. Its rule was *«выбор проекта слева фильтрует блокеры и идеи; без выбора —
всё»*, which disagrees with what is asked for in four places:

| | before | asked for |
|---|---|---|
| blockers when a project is chosen | narrowed to it | everybody's, always |
| ideas when nothing is chosen | every project's | the desk's own |
| a thought with no project, when one is chosen | kept | it belongs to the desk, so not shown |
| who a message is for | whatever the bench and the whole board said | the chosen project by default, the desk with nothing chosen |

And one thing was simply missing: a project with no checkout and no session — added by its address —
had no rows, so a thought typed "about" it was filed under whichever session happened to be first on
the board.

---

## 1 · Blockers are everybody's

> As someone working on one project, I still want to hear that another one has stopped.

**Done when** choosing a project changes nothing in the blocker column.

## 2 · A project can be chosen from its card, without putting it on the bench

> As someone switching to a project, I want one press on its card — not a menu — and I do not want
> the project dropped onto my workbench as a side effect.

**Done when** every project card has a choose button beside its head, pressed state is a fact for a
screen reader, pressing the chosen one chooses none, and the button is not inside the card's
`<summary>` (a control there is swallowed by the disclosure).

## 3 · Ideas are the chosen project's, or the desk's

> As someone who has chosen a project, I want its thoughts; with nothing chosen, the desk's.

**Done when** the idea column shows exactly the chosen project's ideas — every repository of a
declared project — and with nothing chosen, the desk's own and the ones filed before ideas had a
project.

## 4 · A message goes to the chosen project unless the bench says otherwise

> As someone who chose a project, I want "what's broken here?" to be about that project without
> dragging it anywhere.

**Done when** a message with no project in the form takes the chosen one; cards on the bench still
decide first; a thought captured that way is filed under the chosen project even when it has no
session; and with nothing chosen and nothing on the bench, it is the desk's. The column says, in one
sentence, whose ideas these are and who a message is for.

---

## What was deliberately not asked for

**Narrowing the tickets view differently.** The right column's tickets mode is the project's own
tracker board and keeps following the choice, like the ideas it replaces.

**A second, per-tab choice.** One choice for the console, stored, surviving a push — the way it
already was.
