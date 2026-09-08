"""New thread, or continuation of an open one.

docs/04-threads-and-blocks.md: a thread is a subject, and attaching a follow-up to its subject is
what makes "and what about the other one" work — the block inherits the thread's context.

**This module assumes it is wrong sometimes.** It is a small model call on short text with no
ground truth, and the failure is annoying in both directions: a follow-up stranded in its own
thread loses its context, a new subject swallowed into an old one gets answered against the wrong
background. So every decision it makes is visible on the block and reversible in one click, and
every reversal is logged — the correction rate is the number that decides whether this module
should exist at all (docs/09-roadmap.md).

Three rules hold it in place:

- **New is the safe answer**, and it is what a failure produces. Attaching wrongly is the more
  expensive mistake, because it silently changes what a question is answered against.
- **Nothing is merged automatically.** Two subjects that turn out to be one is a judgement, and
  the human makes it.
- **`/new` never reaches here.** When you already know, you should not have to hope.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from agent_desk.answer.session import AnswerFailed, stream_answer
from agent_desk.store.repo import BlockKind, Thread

# The reply is one token, and it is read as one token. Searching the whole reply for a digit was
# worse than useless: "This mentions 2 different files, so: new" attached the block to thread two,
# and so did "Error: rate limited after 2 retries" — the model said new, twice, and was overruled
# by its own prose. Attaching wrongly is the expensive mistake, so anything that is not exactly a
# choice is a new subject.
# `[0-9]` rather than `\d`, which in Python also matches Arabic-Indic and other Unicode digits —
# `int()` accepts those, so `١` would have selected thread one.
_CHOICE = re.compile(r"\A([0-9]{1,2}|new)\Z", re.IGNORECASE)


def prompt(text: str, threads: Sequence[Thread]) -> str:
    lines = [
        "A developer typed one line into a console that watches their Claude Code sessions.",
        "Decide whether it continues one of the open subjects below, or starts a new one.",
        "",
        "Answer with the number of the subject it continues, or the word new. One token, nothing",
        "else. When it is not clearly a continuation, answer new: attaching a question to the",
        "wrong subject changes what it gets answered against, and that is the worse mistake.",
        "",
        "## Open subjects",
    ]
    lines += [f"{index}. {thread.subject}" for index, thread in enumerate(threads, start=1)]
    lines += ["", "## The line", text]
    return "\n".join(lines)


def read_choice(reply: str, threads: Sequence[Thread]) -> str | None:
    """The thread id the reply names, or `None` for a new subject.

    Only the first token is read, and it must be the whole answer once trailing punctuation is
    off it. A reply that says anything else — a sentence, an apology, an error, a number inside a
    sentence — is a decision this module did not understand, and an unparsed decision is a new
    thread rather than a guess at what the model meant.
    """
    words = reply.strip().split()
    if len(words) != 1:
        # One token, and the whole reply. "2 files mention this, so it is new" begins with a digit
        # and ends with the model's actual answer; reading only the first word overruled it just
        # as thoroughly as searching the whole text did.
        return None
    match = _CHOICE.match(words[0].strip(".,:;!?\"'"))
    if match is None or match.group(1).lower() == "new":
        return None
    index = int(match.group(1))
    if 1 <= index <= len(threads):
        return threads[index - 1].id
    return None


async def classify(text: str, threads: Sequence[Thread]) -> str | None:
    """Which open thread this belongs to, or `None`.

    Never raises. A classifier that could fail a submission would be a classifier that makes the
    input field unreliable to keep the threading tidy, which is the wrong trade in a tool whose
    first promise is that typing costs nothing.
    """
    if not threads:
        return None
    try:
        reply = "".join([chunk async for chunk in stream_answer(prompt(text, threads))])
    except (AnswerFailed, OSError):
        return None
    return read_choice(reply, threads)


# --- what was typed, before which subject it belongs to ------------------------------------------
# Three things arrive through one field, and they want three different responses: a question wants
# an answer, a thought wants recording and no second question (docs/05-ideas.md), and "tell Biba to
# run it again" wants a message prepared for a session — prepared, and then stopped, because
# sending is a human click (docs/adr/0002).
#
# `question` is the safe answer here, the way `new` is the safe answer above. A thought answered as
# a question costs one run and loses nothing: the text is in the block, verbatim, and recording it
# is one click away. An instruction read as a question prepares nothing and sends nothing.
_KIND = re.compile(r"\A(question|idea|do|desk|arrange|draw|show|run|unsure)\Z", re.IGNORECASE)

_KIND_OF = {
    "question": "question",
    "idea": "idea",
    "do": "instruction",
    "desk": "master",
    "arrange": "handling",
    "draw": "drawing",
    "show": "showing",
    "run": "running",
    "unsure": "unsure",
}


def kind_prompt(text: str, *, pointed_at: int = 0) -> str:
    """What was typed, and the one boundary that is hard to draw.

    `idea` against `do` is the whole difficulty, and it is not a matter of grammar: in Russian and
    in English alike, a wish about the product is usually phrased as a command. "Make the service
    easy to attach to any project" is a thought about what should exist; "tell Biba to run the
    tests" is somebody being asked to act now. The rule below is the only one that separates them
    reliably — a `do` has an addressee, or it says outright to start.

    The asymmetry matters because the costs are not equal. A thought recorded as an instruction
    starts an agent in a worktree and takes somebody's attention; an instruction recorded as a
    thought sits in the pool until it is clicked. So the doubtful case is an idea.

    `pointed_at` is how many cards were on the workbench when the line was sent, and it is the
    piece that used to be missing. **Dropping an idea onto the workbench and typing "take it on"
    names the thing to act on exactly as clearly as naming a session** — but the classifier only
    ever saw the line, where "бери в работу" is borderline, and the doubtful-case rule then filed
    it as an idea. What the person got was a new parent idea with their ideas hanging under it,
    instead of an agent. That is the bug this argument exists to fix, and it is why the rule below
    is stated as an addressee rather than as a special case.
    """
    pointing = (
        [
            "",
            f"**They had {pointed_at} card{'' if pointed_at == 1 else 's'} on the workbench when "
            "they sent this.** That is an addressee: it is what they are pointing at, and it is "
            "as explicit as naming a session. A line that tells somebody to act on *those* — "
            '"take it on", "бери в работу", "делай", "реализуем" — is `do`, not an idea about '
            "them.",
        ]
        if pointed_at
        else []
    )
    return "\n".join(
        [
            "A developer typed one line into a console that watches their Claude Code sessions.",
            "Say which of these it is. One token, nothing else:",
            "",
            "  question — they want something *from you, now*: an answer, or a thing written for",
            "             them. Both are `question`, because both are answered on the spot and",
            "             neither is filed away for later.",
            '             "what did the migration end up doing", "какие сессии сейчас заняты",',
            '             "напиши мне план внедрения", "составь список того, что осталось",',
            '             "сделай сравнение этих двух подходов", "summarise what changed"',
            "  idea     — they are saying *the product* should exist, or should work differently.",
            "             A wish, proposal, complaint or requirement about the thing being built,",
            "             to be written down and done later.",
            '             "cache the probe results", "сделать так, чтобы сервис подключался',
            '             к любому проекту", "добавить экспорт в CSV", "при внесении идей',
            '             сперва проверять, не под-идея ли это"',
            "  do       — they are telling a named agent, session or project to act, now.",
            '             "tell Biba to run the tests again", "бери в работу", "запусти',
            '             проверку в agent-desk", "сделай это сейчас"',
            "  desk     — they are telling *this console* to act, now: on its own screen, its own",
            "             ideas, its own data, its own behaviour.",
            '             "разгреби текущие идеи", "tidy up the pool", "убери эту колонку",',
            '             "переосмысли и перегруппируй идеи, удали реализованные"',
            "  draw     — they are describing a *process* and asking for it to be drawn: a",
            "             sequence of steps with decisions in it, to appear on the workbench as",
            "             cards. Not a question about a process and not a wish that one existed.",
            '             "нарисуй процесс релиза: сначала тесты, если красные — чиним", "draw me',
            '             the onboarding flow", "изобрази как это работает по шагам"',
            "  show     — they are asking for things that already exist somewhere to be put on",
            "             the workbench as cards: the tickets on a board, the open pull requests.",
            "             Nothing is composed and nothing is decided — a list is fetched and each",
            "             row becomes a card.",
            '             "покажи открытые PR-ы", "покажи тикеты из спринта", "show me the open',
            '             pull requests", "вынеси тикеты на верстак"',
            "  run      — they are telling you to run the drawing that is on the workbench, and",
            "             what they typed is what to run it against. Only when there is a drawing",
            "             there: with an empty workbench the same words are a question.",
            '             "прогони это", "запусти пайплайн на этом тексте", "run it with this",',
            '             "прогони на этом входе"',
            "  arrange  — they are telling you to change *the cards in front of them*: highlight",
            "             some, put these here and those there. The answer is a rearrangement of",
            "             what is already on the workbench, not a paragraph and not a new card.",
            '             "подсвети те, которые могут принести доход", "справа помести идеи для',
            '             простых пользователей, слева для разработчиков", "highlight the ones',
            '             that are blocked", "убери подсветку"',
            "",
            "`desk` is `do` pointed at this program rather than at a project it watches, and it is",
            "the address that decides it. A wish about how this console *should* be one day is",
            'still an idea; "do this to my desk, now" is `desk`.',
            "",
            "**The line between `question` and `idea` is what it is *about*.** An idea is about",
            "the product: after it, the thing being built is different. A `question` is about what",
            "they want in their hands right now: a plan, a list, a summary, a comparison, a draft.",
            '"Напиши мне план" is a plan they want to read — not a wish that the product should',
            'have plans in it. "Add a plans page" is the idea; "write me a plan" is a question.',
            "",
            "**`show` against `question` is whether they asked for the things or for a sentence",
            'about them.** "Покажи открытые PR-ы" wants the pull requests on the workbench;',
            '"сколько у нас открытых PR-ов?" wants a number. `show` is also cheap and undone in one',
            "press, so it can be answered on the balance of it.",
            "",
            "**`arrange` against `question` is whether they asked you to *change* the cards or to",
            '*tell* them something.** "Подсвети те, которые принесут доход" is an arrangement;',
            '"что из этого принесёт доход?" is a question and wants sentences. Both are about the',
            "same cards and reach the same judgement — the difference is only what they asked for.",
            "It is `arrange` only when there are cards on the workbench to arrange; with an empty",
            "workbench the same words are a question.",
            "",
            "**How sure you have to be depends on what it costs to be wrong.** A misread question",
            "costs one wasted answer. A misread `do` or `desk` starts agents in worktrees. So for",
            "those two the bar is high: name them only when there is an addressee or an explicit",
            "instruction to start now, and answer `question` or `idea` when you are weighing it up.",
            "`draw`, `show` and `arrange` are cheap — one model call, undone in one press — and can",
            "be answered on the balance of it. `run` is as expensive as the drawing it runs, and",
            "its guard is different: it needs a drawing on the workbench to be a possible answer",
            "at all, and where there is one it is what the person built it for.",
            "",
            "**There is a seventh answer, and it is only for the expensive ones.** `unsure` — when",
            "this reads as `do` or `desk` and equally as something cheaper, and choosing would be",
            "a coin toss that starts agents. It asks the person which they meant and nothing runs",
            "until they say. Do not answer `unsure` because a line is vague: a vague question is",
            "still a question, and asking about one costs more attention than answering it badly.",
            "Answer it only where the expensive reading is genuinely live.",
            "",
            "Being phrased as a command decides nothing. Almost every request is.",
            "",
            "The line between `idea` and `do` is the other hard one: **`do` needs an addressee, or",
            'an explicit instruction to start now.** A session\'s name, "this project", "take it',
            'on", "бери в работу", "запусти", "сделай сейчас". A wish with nobody named is an',
            "idea, however imperative it sounds.",
            "",
            "Two tie-breaks, and they pull in different directions on purpose, because the two",
            "mistakes cost different things:",
            "",
            "  * Unsure between `idea` and `do` — answer `idea`. A thought taken as an instruction",
            "    starts an agent nobody asked for; an instruction taken as a thought waits one",
            "    click.",
            "  * Unsure between `idea` and `question` — answer `question`. A request taken as an",
            "    idea is silently *not done*: what they asked for never gets written, and it goes",
            "    into a list of things to build instead. A question taken as an idea is a wasted",
            "    answer and one line to delete.",
            *pointing,
            "",
            "## The line",
            text,
        ]
    )


def read_kind(reply: str) -> BlockKind:
    """The kind the reply names, or `question` when it named nothing this understands."""
    words = reply.strip().split()
    if len(words) != 1:
        return "question"
    match = _KIND.match(words[0].strip(".,:;!?\"'"))
    if match is None:
        return "question"
    return _KIND_OF[match.group(1).lower()]  # type: ignore[return-value]


async def kind(text: str, *, pointed_at: int = 0) -> BlockKind:
    """What one line of input is. Never raises, for the reason `classify` never does.

    `pointed_at` is how many cards were on the workbench: what somebody is pointing at is part of
    what they said, and leaving it out is what made "бери в работу" over two dropped ideas produce
    a third idea instead of an agent.
    """
    try:
        reply = "".join(
            [chunk async for chunk in stream_answer(kind_prompt(text, pointed_at=pointed_at))]
        )
    except (AnswerFailed, OSError):
        return "question"
    return read_kind(reply)


# --- which of the thoughts already written down does this touch ---------------------------------
# A request for work is often a thing somebody already had an idea about, and the console can say
# so: "this looks like it is about these three — implement them?" It is a guess, so it is rendered
# as an offer with a button, never as a fact and never as an action (docs/05-ideas.md).
_NUMBERS = re.compile(r"\A[0-9, ]+\Z")


# How much of a card's own line the reader is shown. The card says this much on the bench, so the
# choice is made from what the person can see — a reading made from more than is on screen is one
# nobody watching can follow.
CARD_CHARS = 80

# One token, read whole — the same shape as `_CHOICE` and for the same reason. "It follows on from
# 2 of the three" is not an answer, and reading a digit out of it would attach a question to a card
# nobody named. Several numbers are a token too: "1,3" is one answer naming two cards, and the
# comma is the only thing allowed between them.
_WHICH = re.compile(r"\A((?:[0-9]{1,2},)*[0-9]{1,2}|none)\Z", re.IGNORECASE)

# How many cards one question is allowed to follow on from. The product here is lines on a diagram,
# and six lines into one card is a picture nobody reads — which is the thing an enquiry bench is
# for. The instruction says three as well; this is here because an instruction is not a guarantee.
MOST_CARDS = 3


def about_prompt(text: str, cards: Sequence[str]) -> str:
    """Which card on the bench this question follows on from.

    "В зависимости от моего следующего вопроса он крепится либо к предыдущему ответу, либо к
    описанию, либо вообще имеет другую область."

    The third outcome is the one the instruction spends its words on. Without it every enquiry
    collapses into one long branch — each question read as following the last, because the last is
    always *something* — and that is the feed the workbench exists to stop being.
    """
    lines = [
        "A developer is thinking on a workbench of cards. They have just typed a question.",
        "Decide which cards it follows on from, if any.",
        "",
        "Answer with the number of that card, or several numbers separated by commas when the",
        f"question is about more than one of them — at most {MOST_CARDS}. Or the word none. One",
        "token, nothing else. Answer none whenever it is not clearly about any of them: a question",
        "is allowed to open a subject of its own, and that is more common than it looks.",
        "",
        "## The cards",
    ]
    lines += [f"{index}. {card[:CARD_CHARS]}" for index, card in enumerate(cards, start=1)]
    lines += ["", "## The question", text]
    return "\n".join(lines)


def read_which(reply: str, count: int) -> list[int]:
    """The 1-based cards the reply names, in the order it named them, or empty for none of them.

    Shared by every question of the shape "which of these, if any" — which card a question follows
    on from, which cards somebody asked to be brought over. One reader, because the ways a model
    can fail to name a card are the same ways whatever it was asked.

    "Я могу сразу попросить нарисовать условно 5 частей… и задавать одновременно различные
    вопросы." A question about two of the parts has two cards above it, which makes this a graph
    rather than a tree — and a reader that could only ever say one number is what would have kept
    it a tree whatever the person asked.

    Out of range is dropped rather than an error: a model that answers 7 out of 3 has not chosen a
    card, and drawing a line to whichever card happens to be third would be inventing one. A reply
    that is entirely out of range is therefore none, which is the safe answer anyway.
    """
    said = reply.strip().strip(".").strip()
    found = _WHICH.match(said)
    if found is None or said.lower() == "none":
        return []
    named = [int(one) for one in found.group(1).split(",")]
    # Deduplicated, because "1,1" names one card twice and two lines between the same pair of cards
    # are one line drawn twice.
    picked: list[int] = []
    for which in named:
        if 1 <= which <= count and which not in picked:
            picked.append(which)
    return picked[:MOST_CARDS]


def wanted_prompt(text: str, cards: Sequence[str]) -> str:
    """Which of the things on the board somebody is asking to be brought over.

    "Нужно «принеси сюда сессию, которая чинит парсер» — то есть найти по смыслу и положить, одним
    предложением." Ctrl+K already matches a label; this is the same act by meaning, which is what
    a person has when they cannot remember what a session called itself.
    """
    lines = [
        "A developer asked for something on their board to be put on their workbench.",
        "Decide which of the things below they mean.",
        "",
        "Answer with the number, or several numbers separated by commas when they clearly asked",
        f"for more than one — at most {MOST_CARDS}. Or the word none. One token, nothing else.",
        "Answer none when nothing here is what they described: bringing the wrong card over is a",
        "worse answer than bringing none, because they then have to notice it is wrong.",
        "",
        "## What is on the board",
    ]
    lines += [f"{index}. {card[:CARD_CHARS]}" for index, card in enumerate(cards, start=1)]
    lines += ["", "## What they asked for", text]
    return "\n".join(lines)


async def wanted(text: str, cards: Sequence[str]) -> list[int]:
    """The things on the board this asks for, 1-based, or empty."""
    if not cards:
        return []
    try:
        reply = "".join([chunk async for chunk in stream_answer(wanted_prompt(text, cards))])
    except (AnswerFailed, OSError):
        return []
    return read_which(reply, len(cards))


async def about(text: str, cards: Sequence[str]) -> list[int]:
    """The cards this question follows on from, 1-based, or empty.

    A failure is none, like everywhere else in this module: no line drawn is a bench somebody
    joins up themselves, and a line drawn from a failed reading is one they have to notice first.
    """
    if not cards:
        return []
    try:
        reply = "".join([chunk async for chunk in stream_answer(about_prompt(text, cards))])
    except (AnswerFailed, OSError):
        return []
    return read_which(reply, len(cards))


def related_prompt(text: str, ideas: Sequence[str]) -> str:
    lines = [
        "A developer asked for some work to be done. Below are ideas they wrote down earlier.",
        "Say which of them this request is about — by number, comma-separated, and nothing else.",
        "Answer `none` when it is about none of them.",
        "",
        "Be strict: an idea belongs in the answer only if doing this request would build it or",
        "most of it. Two things that are merely in the same area are not the same idea, and a",
        "wrong number here puts somebody else's thought in front of a button that says built.",
        "",
        "## The ideas",
    ]
    lines += [f"{index}. {idea}" for index, idea in enumerate(ideas, start=1)]
    lines += ["", "## The request", text]
    return "\n".join(lines)


def read_related(reply: str, count: int) -> list[int]:
    """The numbers the reply names, in range and without repeats. Anything else is none."""
    answer = reply.strip().rstrip(".")
    if not answer or not _NUMBERS.match(answer):
        return []
    picked: list[int] = []
    for part in answer.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= count and int(part) not in picked:
            picked.append(int(part))
    return picked


async def related(text: str, ideas: Sequence[str]) -> list[int]:
    """Which ideas this request is about. Never raises: an unavailable model means none of them."""
    if not ideas:
        return []
    try:
        reply = "".join([chunk async for chunk in stream_answer(related_prompt(text, ideas))])
    except (AnswerFailed, OSError):
        return []
    return read_related(reply, len(ideas))
