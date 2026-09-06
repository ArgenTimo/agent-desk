# The plan, from the pool

Twenty-three ideas, all of them about this console. Written down as one order of work rather than
twenty-three, because half of them are the same piece of work seen from different angles and doing
them separately would mean building the same thing twice.

Order is by what unblocks the most, not by what is easiest.

## 1 · What a card says, and how much of it

*Ideas: the three views; "хинт по умолчанию"; "метадата — созданное ЛЛМ описание"; "фул-дата
только по нажатию"; "название и содержание блокеров и идей должны быть грамотно сформированы ЛЛМ и
точно передавать суть"; "исходное сообщение можно посмотреть при детальном рассмотрении".*

First because it changes every card on the board, and everything below is read through it.

- **Hint is the default.** A very short line anybody can read. Today a card opens showing its
  metadata, which is more than a glance wants.
- **Metadata is written, not extracted.** A sentence a model wrote about *this* element — what
  this project is, what this session is doing — cached, so a board of twenty cards is not twenty
  model calls a second.
- **Full is everything and only on purpose**: the console, how long it has been up, tokens, and —
  for an idea or a blocker — the message or ticket it came from, verbatim.

## 2 · What a card counts

*Idea: "показывать к-во закрытых и заблокированных задач у каждого проекта/инстанса/сессии/агента".*

The counts exist for projects. They are wanted per session, per instance and per agent, which is
where "who has actually done anything" is answered.

## 3 · A blocker that can be cleared

*Idea: "сколько задач он блокирует, сколько примерно займёт снятие, кнопка «разблокировано» →
статус уточнения → агент проверяет → только тогда уходит".*

The column is real; the card is thin. This adds the three things that make it actionable, and one
that makes it trustworthy: pressing "unblocked" does not delete the blocker, it asks for it to be
checked.

## 4 · Pull requests as blockers

*Ideas: "в качестве блокеров могут висеть PR с github которые ожидают ревью/апрува/мержа, для тех
проектов которые подключили гитхаб как коннектор".*

The same shape as the Jira reader ([`adr/0010`](adr/0010-reading-a-tracker-back.md)): read only,
marked as coming from elsewhere, and only where somebody named a credential.

## 5 · A deferred task that actually fires

*Idea: "отложенная задача… вычисляем нужный момент и делаем, либо напомни мне завтра".*

Today a deferred task is a task nobody started. It needs a moment — computed or named — and
something that watches for it.

## 6 · The small ones

*Ideas: Ctrl+L folding the chat with a way back; a chat tab whose name follows the conversation.*

## 7 · The ones that need a judgement

*Ideas: "сервис сам определяет, исполнена ли идея" — against filings, the queue and the code
rather than against its own text; the canary leading to an action; the break-resume prompt built
from what the session was actually doing; approval producing a *list* of tickets.*

Grouped because each is a model call with a fact behind it, and each is only worth having if the
fact is checked rather than guessed.

## 8 · A folder on the workbench

*Idea: "по ПКМ добавить папку с устройства — каждый файл мини-карточка, и ЛЛМ пишет что каждый
файл делает".*

Read-only, like everything else this program does with somebody's disk.

## 9 · "Go to it", properly

*Idea: the button should open the session on screen.*

Last because it cannot be done from a page alone, and the honest options — a small local helper, a
registered URL scheme — are each larger than they look.
