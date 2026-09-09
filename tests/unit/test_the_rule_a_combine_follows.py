"""What "put these two together" means, and where that is decided.

"В алхимии вода + огонь = пар. В работе две карточки + вопрос = новый документ. Правило — это то,
что превращает пару в третье, и оно должно быть видимым и сменяемым: одна и та же пара в разных
правилах даёт разное."

The gesture already existed and asked one hardcoded thing. That is fine for the first combine
somebody tries and wrong for the second: two cards put together to draft a document and the same
two put together to find what they disagree about are one gesture and two questions.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk import combining
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
BOARD = HERE / "agent_desk" / "web" / "templates" / "board.html"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


# --- the rule itself --------------------------------------------------------------------------
def test_saying_nothing_is_the_console_s_own_rule() -> None:
    """A bench nobody has told anything still combines, and asks what the console documents."""
    assert combining.rule("") == combining.DEFAULT
    assert combining.rule("   \n ") == combining.DEFAULT


def test_a_rule_somebody_set_is_what_is_asked() -> None:
    assert combining.rule("  find what they disagree about  ") == "find what they disagree about"


def test_too_much_is_trimmed_rather_than_refused() -> None:
    """Somebody who pasted a document gets a rule that is too long by the end and still works,
    which beats a gesture that stops working until they go and edit it."""
    said = combining.rule("x" * (combining.MOST_CHARS + 500))

    assert len(said) == combining.MOST_CHARS


# --- and where it lives ------------------------------------------------------------------------
async def test_a_bench_keeps_its_own_rule(desk: Store) -> None:
    """Per workbench, not per pair: "иначе на каждое соединение придётся объяснять заново"."""
    await desk.combine_with("t1", "draft a document from them")
    await desk.combine_with("t2", "find what they disagree about")

    assert await desk.combining("t1") == "draft a document from them"
    assert await desk.combining("t2") == "find what they disagree about"


async def test_clearing_it_is_the_same_as_never_having_set_it(desk: Store) -> None:
    """Two spellings of "the default" is one that somebody eventually has to reconcile."""
    await desk.combine_with("t1", "something else")

    await desk.combine_with("t1", "   ")

    assert await desk.combining("t1") == ""
    assert combining.rule(await desk.combining("t1")) == combining.DEFAULT


async def test_a_bench_that_was_never_told_says_so(desk: Store) -> None:
    assert await desk.combining("nobody") == ""


# --- and that the page does not hold a second copy of it ----------------------------------------
def test_the_page_does_not_carry_the_wording() -> None:
    """A copy in the page would be a second answer to "what does combining mean", and the two
    would part company the first time one of them moved."""
    source = _code()

    assert "HOW_TO_COMBINE" not in source
    assert "Make one thing out of these two" not in source
    assert "text:" not in _body_of("combine"), "the drag still sends words of its own"


def _body_of(name: str) -> str:
    source = _code()
    start = source.index(f"function {name}(")
    return source[start : source.index("\n}\n", start)]


def test_the_rule_is_read_where_the_gesture_is_answered() -> None:
    route = (HERE / "agent_desk" / "web" / "routes.py").read_text(encoding="utf-8")

    assert "typed = combining.rule(await store.combining(" in route


def test_it_can_be_read_before_it_is_used_and_changed() -> None:
    """ "Оно должно быть видимым и сменяемым." A tooltip is where somebody looks to find out what a
    control does, so it is where "what will this ask" belongs; the menu item is the other half."""
    assert 'data-add="combining"' in BOARD.read_text(encoding="utf-8")
    assert "function howCombiningWorks(" in _code()
    assert "function sayWhatCombiningAsks(" in _code()
    assert "if (name === 'mix') sayWhatCombiningAsks();" in _code()


async def test_the_same_pair_under_two_rules_asks_two_things(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole claim of the idea, and the reason a rule is a thing at all. Asserted against what
    the route hands to `submit`, because that is what the model is actually sent."""
    asked: list[str] = []
    thread = await desk.create_thread("a chat")

    async def caught(store: Store, typed: str, rows: object, **rest: object) -> object:
        asked.append(typed)
        return await desk.create_block(
            thread_id=thread.id, kind="question", input=typed, thread_set_by="human"
        )

    monkeypatch.setattr(routes.block_runs, "submit", caught)
    monkeypatch.setattr(routes, "board", lambda: ([], ""))

    for rule in ("draft a document from them", "find what they disagree about"):
        await desk.combine_with(thread.id, rule)
        await routes.ask(
            _a_form(thread=thread.id, gesture="combine", made_from="idea%3Aa%2Cidea%3Ab")
        )

    assert asked == ["draft a document from them", "find what they disagree about"]


def _a_form(**fields: str) -> object:
    body = "&".join(f"{name}={value}" for name, value in fields.items()).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()


# --- the same pair gives the same thing ---------------------------------------------------------
async def _a_combine(desk: Store, thread: str, made_from: str, said: str, answer: str) -> str:
    block = await desk.create_block(
        thread_id=thread, kind="question", input=said, thread_set_by="human"
    )
    await desk.made_out_of(block.id, made_from.split(","))
    await desk.finish_block(block.id, answer)
    return block.id


async def test_the_same_pair_is_remembered(desk: Store) -> None:
    """ "Иначе это не мир, а генератор случайностей: собрал то же самое и получил другое.\" """
    thread = await desk.create_thread("a chat")
    made = await _a_combine(desk, thread.id, "a,b", combining.DEFAULT, "steam")

    before = await desk.combined_before(thread.id, ["a", "b"], combining.DEFAULT)

    assert before is not None and before.id == made


async def test_either_order_is_the_same_pair(desk: Store) -> None:
    """Dragging A onto B and B onto A is one act to the person doing it. The stored order stays the
    order of the gesture — that is provenance — but it is not what this asks by."""
    thread = await desk.create_thread("a chat")
    await _a_combine(desk, thread.id, "a,b", combining.DEFAULT, "steam")

    before = await desk.combined_before(thread.id, ["b", "a"], combining.DEFAULT)

    assert before is not None


async def test_a_different_rule_is_a_different_question(desk: Store) -> None:
    """The same pair under two rules is two questions, and showing the first one's answer to the
    second would be worse than asking again."""
    thread = await desk.create_thread("a chat")
    await _a_combine(desk, thread.id, "a,b", combining.DEFAULT, "steam")

    assert await desk.combined_before(thread.id, ["a", "b"], "find the disagreement") is None


async def test_an_answer_that_never_came_is_not_a_memory(desk: Store) -> None:
    """A run that failed or is still going has nothing to show, and offering it as "you already
    made this" would be the console reporting a status it does not have."""
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input=combining.DEFAULT, thread_set_by="human"
    )
    await desk.made_out_of(block.id, ["a", "b"])

    assert await desk.combined_before(thread.id, ["a", "b"], combining.DEFAULT) is None


async def test_another_bench_is_not_asked_about(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    other = await desk.create_thread("another")
    await _a_combine(desk, thread.id, "a,b", combining.DEFAULT, "steam")

    assert await desk.combined_before(other.id, ["a", "b"], combining.DEFAULT) is None


async def test_the_console_answers_with_the_card_it_already_has(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    made = await _a_combine(desk, thread.id, "a,b", combining.DEFAULT, "steam and nothing else")

    answer = await routes.what_these_two_already_made(thread=thread.id, pair="a,b")

    assert made in answer.body.decode()
    assert "steam and nothing else" in answer.body.decode()


async def test_a_pair_that_has_made_nothing_says_nothing(desk: Store) -> None:
    thread = await desk.create_thread("a chat")

    answer = await routes.what_these_two_already_made(thread=thread.id, pair="a,b")

    assert answer.body.decode() == "{}"


def test_asking_again_is_a_gesture_and_not_a_deletion() -> None:
    """Without it a pair answers once and for ever, and "try it another way" would mean throwing
    the first answer away first."""
    source = _code()

    assert "again: event.shiftKey" in source
    assert "if (!again) {" in _body_of("combine")
    assert "Shift for another answer" in BOARD.read_text(encoding="utf-8")


def test_a_check_that_failed_does_not_stop_the_gesture() -> None:
    """Worst case it is asked twice, which is what it did before this existed."""
    assert "return {};" in _body_of("alreadyMade")


async def test_setting_the_rule_says_what_it_now_asks(desk: Store) -> None:
    """The reply is the rule in force, not an acknowledgement: somebody who mistyped finds out
    from the answer rather than from the next combine."""
    thread = await desk.create_thread("a chat")

    answer = await routes.set_what_a_combine_asks(
        _a_form(thread=thread.id, said="find+the+disagreement")
    )

    assert "find the disagreement" in answer.body.decode()
    assert await desk.combining(thread.id) == "find the disagreement"


async def test_clearing_it_says_it_went_back(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    await desk.combine_with(thread.id, "something else")

    answer = await routes.set_what_a_combine_asks(_a_form(thread=thread.id, said=""))

    assert '"its_own":false' in answer.body.decode()
    assert await desk.combining(thread.id) == ""


async def test_a_rule_with_no_workbench_to_belong_to_is_refused(desk: Store) -> None:
    """A rule belongs to one bench, and a chat nobody has opened is not one."""
    answer = await routes.set_what_a_combine_asks(_a_form(said="anything"))

    assert "Open a chat first" in answer.body.decode()


async def test_one_card_is_not_a_pair(desk: Store) -> None:
    """The check is asked with whatever the page had. Half a gesture is not a question."""
    assert await desk.combined_before("t1", ["a"], combining.DEFAULT) is None

    answer = await routes.what_these_two_already_made(thread="t1", pair="a")

    assert answer.body.decode() == "{}"


# --- and it all goes on a shelf -----------------------------------------------------------------
async def test_what_was_made_here_is_listed_newest_first(desk: Store) -> None:
    """ "Полученные элементы — это библиотека, а не разовые карточки. Без места, где они лежат,
    «бесконечная» игра заканчивается на том, что предыдущее потерялось за краем верстака.\" """
    thread = await desk.create_thread("a chat")
    first = await _a_combine(desk, thread.id, "a,b", combining.DEFAULT, "steam")
    second = await _a_combine(desk, thread.id, "c,d", combining.DEFAULT, "mud")

    made = await desk.made_here(thread.id)

    assert [one.id for one in made] == [second, first]


async def test_an_ordinary_answer_is_not_on_the_shelf(desk: Store) -> None:
    """The shelf is what cards made, not what the chat said. Everything else is the conversation,
    which has a column of its own."""
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="hello", thread_set_by="human"
    )
    await desk.finish_block(block.id, "hello back")

    assert await desk.made_here(thread.id) == []


async def test_a_combine_that_failed_is_not_a_thing_that_exists(desk: Store) -> None:
    """Listing it on a shelf of what was made would be reporting a status nobody has."""
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input=combining.DEFAULT, thread_set_by="human"
    )
    await desk.made_out_of(block.id, ["a", "b"])
    await desk.fail_block(block.id, "it stopped")

    assert await desk.made_here(thread.id) == []


async def test_the_shelf_says_what_each_one_was_made_of(desk: Store) -> None:
    """A shelf of twenty answers that says only what each one is called is a shelf nobody reads."""
    thread = await desk.create_thread("a chat")
    await _a_combine(desk, thread.id, "idea:a,idea:b", combining.DEFAULT, "steam\nand more")

    answer = await routes.what_this_bench_has_made(thread=thread.id)
    (one,) = json.loads(answer.body)["made"]

    assert one["label"] == "steam", "the label is not the first line of what it says"
    assert one["from"] == ["idea:a", "idea:b"]


def test_the_shelf_is_rebuilt_every_time_the_menu_opens() -> None:
    """A list kept in step by hand is a list that offers a card somebody took off an hour ago."""
    source = _code()
    start = source.index("function showMenu(")
    body = source[start : source.index("\n}\n", start)]

    assert "showShelf();" in body


# --- and it has to be cheap, because it happens often -------------------------------------------
async def _prompt_for(desk: Store, monkeypatch: pytest.MonkeyPatch, *, a_gesture: bool) -> str:
    """What the answer engine is actually handed. Measured rather than reasoned about."""
    from agent_desk.web import blocks

    sent: list[str] = []

    async def caught(store: Store, block: object, prompt: str, dirs: object) -> None:
        sent.append(prompt)

    monkeypatch.setattr(blocks, "_run", caught)

    thread = await desk.create_thread("a chat")
    earlier = await desk.create_block(
        thread_id=thread.id, kind="question", input="what came before", thread_set_by="human"
    )
    await desk.finish_block(earlier.id, "an answer nobody asked this time")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input=combining.DEFAULT, thread_set_by="human"
    )

    await blocks._classify_and_answer(
        desk, block, [], classify=False, a_gesture=a_gesture, surface=["1. water", "2. fire"]
    )
    return sent[0]


async def test_a_combine_does_not_carry_the_conversation(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Соединение стоит один вызов и происходит часто… дёшево и быстро." By the tenth combine the
    thread is nine answers long and every one of them was travelling with the eleventh question,
    which is the whole cost. The two cards are in the prompt as the workbench — that is what was
    pointed at."""
    said = await _prompt_for(desk, monkeypatch, a_gesture=True)

    assert "an answer nobody asked this time" not in said
    assert "water" in said and "fire" in said, "it stopped carrying the two cards as well"


async def test_a_typed_question_still_carries_it(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The carve-out is for gestures. Attaching a follow-up to a subject is only worth anything if
    the subject then travels with it (docs/04-threads-and-blocks.md)."""
    said = await _prompt_for(desk, monkeypatch, a_gesture=False)

    assert "an answer nobody asked this time" in said


def test_a_combine_is_not_aimed_at_the_whole_board() -> None:
    """`aim` falls back to everything when the cards it was pointed at are not sessions — which two
    ideas never are — so every session on the machine was being described to a question that had
    nothing to do with any of them."""
    source = (HERE / "agent_desk" / "web" / "blocks.py").read_text(encoding="utf-8")
    start = source.index("    aimed, about = aim(rows, project, session, targets)")
    after = source[start : start + 700]

    assert "if a_gesture:" in after
    assert 'aimed, about = [], ""' in after
