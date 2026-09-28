# 10 · A project as it actually is

Written from what the author asked for, in their words, and checked against what the board already
does before a line of it was built:

> проект объединён общим git репозиторием, проект делится на инстансы — это копии проекта на
> устройстве, внутри каждого инстанса существуют сессии ллм. А также есть фоновые сессии — они
> должны находиться под тем инстансом, с которым работают в данный момент. Также сессии способны
> поднимать агентов внутри себя — их тоже необходимо указывать как дочерние объекты сессии. …
> Фоновые и терминальные сессии должны иметь своё визуальное различие.

## What was already true

| asked for | already there |
|---|---|
| a project can be added and watched with no checkout here and no session in it | yes — `/projects/attach` takes a URL and records an address, and a seen project stays on the board after its last session ends (073) |
| a project is one git repository | yes — `observe/shape.py` keys a checkout by its origin, and every worktree of it resolves to the same key |
| a project is split into instances, each a copy on this machine | yes — an instance is one working directory |
| sessions live inside an instance | yes |

## What was not

**A background session was not under the instance it works in.** `claude --bg --worktree <name>`
runs in `<checkout>/.claude/worktrees/<name>`, and the board grouped by working directory — so every
background agent became an instance of its own, beside the checkout it was working on rather than
inside it. On the author's board that was twenty-three "instances" for one checkout.

**An agent a session started was a chip, not a child.** The transcript already records every
`Agent` call and whether it came back; the board drew them as a row of tags at the bottom of the
card, indistinguishable from the other pills on it.

**Background and terminal looked alike.** A background session's dot was a different blue and
nothing else said so. The difference is not cosmetic: one of them can be written to from here and
the other cannot (docs/adr/0009), and a person deciding whether to type into a card has to be able
to tell which it is without reading a sentence at the bottom.

---

## 1 · A background session sits under the checkout it works in

> As someone with an agent working in a worktree of my checkout, I want to find it under that
> checkout, because that is where its work is going to land.

**Done when** a session in `<checkout>/.claude/worktrees/<name>` is shown inside the `<checkout>`
instance, still saying which worktree it is in — and a separate checkout of the same repository
somewhere else on the machine is still an instance of its own, because that *is* another copy.

## 2 · An agent is a child of the session that started it

> As someone looking at a session, I want the agents it has started listed under it as things of
> their own — what each was asked to do and whether it has come back.

**Done when** every agent the transcript shows is a child node of its session, running ones first.

## 3 · Background and terminal are told apart at a glance

> As someone about to type into a card, I want to know before I read anything whether this session
> can hear me.

**Done when** every session card says which kind it is in its head, and the two kinds are drawn
differently — by shape and a word, not only by a colour, because colour on this page means status.

---

## What was deliberately not asked for

**Writing into a terminal session.** There is no client for it; docs/adr/0002 and 0009 say why a
guessed frame is not one.

**Guessing which instance a session outside any checkout belongs to.** A session is placed under a
checkout only when its directory is inside that checkout. Anything else stays where its directory
says it is.
