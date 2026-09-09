"""Two cards make a third.

"Создал условно 4 карточки с элементами, а дальше за счёт интерфейса могу получать и комбинировать
новые элементы и изделия."

The words that decide the shape are «за счёт интерфейса». Not a request typed into the field with
two card names in it — a gesture: drag one card onto another and the third appears. And what
appears is an ordinary card, so it can be dragged onto a fourth.
"""

from __future__ import annotations

import html.parser
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import Store

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
CONSOLE = HERE / "agent_desk" / "web" / "static" / "console.js"
CSS = HERE / "agent_desk" / "web" / "static" / "console.css"
BOARD = HERE / "agent_desk" / "web" / "templates" / "board.html"


def _code() -> str:
    return "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def _body(name: str) -> str:
    source = _code()
    start = source.index(f"function {name}(")
    return source[start : source.index("\n}\n", start)]


def test_combining_is_a_tool_and_not_a_held_key() -> None:
    """A plain drop onto another card cannot mean this: parking one card over another is something
    people do by accident every minute on a bench they drag around all day. A held key would have
    worked and nobody would ever have found it, which is the argument that put the strip here."""
    markup = BOARD.read_text(encoding="utf-8")

    assert 'data-tool="mix"' in markup
    assert "Combine —" in markup and "(X)" in markup
    assert "mix: 'Combine'" in _code()


def test_the_tool_that_combines_does_not_also_move_the_card() -> None:
    """The card stays where it is: the drag is the gesture, not a move. A card that slid across the
    bench every time somebody combined it would have to be put back by hand each time."""
    assert "if (tool !== 'move' && pin) return;" in _code()


def test_the_card_it_would_land_on_is_marked_before_the_release() -> None:
    """Otherwise the answer to "which one am I about to combine this with" arrives after the act."""
    assert "classList.add('to-mix')" in _body("markToMix")
    assert ".pin.to-mix {" in CSS.read_text(encoding="utf-8")


def test_a_release_over_nothing_combines_nothing() -> None:
    """Letting go over bare bench is how somebody changes their mind, and it has to be free."""
    source = _code()
    start = source.index("window.addEventListener('pointerup', (event) => {\n  if (!mixing)")
    body = source[start : source.index("\n});", start)]

    assert "if (onto) combine(" in body


def test_what_comes_back_is_an_ordinary_card_and_not_an_idea() -> None:
    """ "Бесконечную динамичную адаптивную" — the third thing has to be combinable again, so it is
    the same kind of card as everything else. And it is not written into the pool: whether a thing
    made on the bench is worth keeping is a separate press, which the pool already has."""
    body = _body("combine")

    assert "button: 'yes'" in body, "a combine draws a card for the question nobody reads twice"
    assert "/blocks" in body
    assert "/ideas" not in body and "keepThisAsAnIdea" not in body


def test_only_the_two_cards_are_what_it_is_about() -> None:
    """The gesture names its two cards, so the message carries those and not whatever else the
    bench happened to be carrying."""
    body = _body("combine")

    assert "targets: [from, onto].join(',')" in body
    assert "pinnedTargets()" not in body


def test_the_third_card_lands_under_the_two_that_made_it() -> None:
    """A third card that appears in the next free slot is a card nobody connects to the gesture
    that made it — and the gesture is the whole of what "за счёт интерфейса" means."""
    body = _body("answerCard")

    assert "article.dataset.madeFrom" in body
    assert "spotUnder(mixed)" in body
    assert "says: 'makes'" in body, "the two lines do not say what they are"


def test_the_pair_survives_a_reload() -> None:
    """The first version held it in a `Map` in the page. It worked until a refresh, after which the
    third card sat joined to nothing — and provenance that disappears when you reload is decoration
    rather than a connection. It is on the block now, so the page reads it back like anything else."""
    source = _code()

    assert "made_from: [from, onto].join(',')" in _body("combine")
    assert "new Map()" not in _body("combine")
    assert "mixedFrom" not in source, "the pair is still being remembered in the browser"
    assert "data-made-from" in (
        HERE / "agent_desk" / "web" / "templates" / "_blocks.html"
    ).read_text(encoding="utf-8")


def test_what_two_cards_made_is_not_filed_as_a_guess() -> None:
    """`relates_to` is the right shape and the wrong claim: it is documented as a reading, a short
    run's guess at what a typed question follows on from. Two cards dragged together is a fact, and
    a known thing filed where everything is a guess cannot be told from a guess afterwards."""
    route = (HERE / "agent_desk" / "web" / "routes.py").read_text(encoding="utf-8")
    start = route.index('by_button = str(form.get("button"')
    submit = route[start : route.index("\n@router", start)]

    assert "made_out_of(made.id, combined)" in submit
    assert "set_block_relates_to" not in submit
    assert "len(combined) == 2" in submit, "a combine is two cards, and anything else is not one"


def test_the_line_it_draws_is_one_of_the_kinds_there_are() -> None:
    """Six kinds and no seventh: a line that says something the server has never heard of is a line
    that cannot be read back, changed, or reasoned about."""
    kinds = (HERE / "agent_desk" / "ties.py").read_text(encoding="utf-8")
    start = kinds.index("KINDS")

    assert '"makes"' in kinds[start : kinds.index("\n\n", start)]


def test_the_tool_strip_still_holds_one_icon_shape() -> None:
    """A fourth icon drawn a fourth way is the crooked column back again."""

    class Read(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.boxes: set[str | None] = set()
            self.inside = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            got = {name: value or "" for name, value in attrs}
            if tag == "button" and "data-tool" in got:
                self.inside = True
            elif tag == "svg" and self.inside:
                self.boxes.add(got.get("viewBox"))

        def handle_endtag(self, tag: str) -> None:
            if tag == "button":
                self.inside = False

    read = Read()
    read.feed(BOARD.read_text(encoding="utf-8"))

    assert len(read.boxes) == 1, f"the icons are drawn in different boxes: {read.boxes}"


# --- and it is written down, because a refresh must not undo a gesture ---------------------------
@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


async def test_the_block_remembers_the_two_cards(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="make one of these", thread_set_by="human"
    )

    await desk.made_out_of(block.id, ["idea:one", "idea:two"])

    again = await desk.block(block.id)
    assert again is not None and again.made_from == "idea:one,idea:two"


async def test_an_ordinary_message_was_made_out_of_nothing(desk: Store) -> None:
    """Empty rather than absent: every block has the column, and only a combine fills it."""
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="hello", thread_set_by="human"
    )

    again = await desk.block(block.id)
    assert again is not None and again.made_from == ""


async def test_the_order_of_the_gesture_is_kept(desk: Store) -> None:
    """The card that was dragged, then the card it was dropped on. Water on fire and fire on water
    are the same pair and not the same sentence, and the rule that reads them may care."""
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="x", thread_set_by="human"
    )

    await desk.made_out_of(block.id, ["b", "a"])

    again = await desk.block(block.id)
    assert again is not None and again.made_from == "b,a"


# --- and the markup that carries it says four things and not two --------------------------------
def _article_attributes(**block: object) -> set[str]:
    """The attribute names a browser reads off the rendered article.

    Rendered and then parsed, rather than matched against the template's source: what went wrong
    here was invisible in the source and only existed after Jinja had joined the lines.
    """
    from agent_desk.web.routes import env

    said = env.from_string(
        (HERE / "agent_desk" / "web" / "templates" / "_blocks.html")
        .read_text(encoding="utf-8")
        .split('<div class="said">')[0]
        + "</article>{% endfor %}"
    ).render(blocks=[type("B", (), block)()])

    class Read(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.names: set[str] = set()

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "article":
                self.names = {name for name, _ in attrs}

    read = Read()
    read.feed(said)
    return read.names


def test_a_settled_combine_carries_all_four_facts() -> None:
    """`trim_blocks` and `lstrip_blocks` eat the newline after `endif` and the indent before the
    next tag, so two conditional attributes in a row came out with nothing between them:
    `data-settleddata-relates="…"` is one attribute with a very long name. It had already cost
    `data-settled` on every block the classifier had read — silently, because malformed markup does
    not raise, it parses into something else."""
    names = _article_attributes(
        id="b1",
        state="answered",
        kind="question",
        relates_to="idea:one",
        by_button=True,
        made_from="idea:one,idea:two",
        thread_id="t1",
    )

    assert names == {
        "class",
        "data-block",
        "data-settled",
        "data-relates",
        "data-by-button",
        "data-made-from",
        "data-thread",
    }


def test_a_plain_message_carries_only_what_is_true_of_it() -> None:
    names = _article_attributes(
        id="b2",
        state="asked",
        kind="question",
        relates_to="",
        by_button=False,
        made_from="",
        thread_id="t1",
    )

    assert names == {"class", "data-block", "data-thread"}


# --- and the third card can be dragged onto a fourth --------------------------------------------
async def test_a_result_card_named_by_the_gesture_is_on_the_bench(desk: Store) -> None:
    """ "Бесконечную динамичную адаптивную." Found by combining twice in a browser: the second
    combine answered "there is still only one card in front of you", because an answer card is left
    out of the digest as half of the conversation. That rule is right for a card the message merely
    carried and wrong for a card a gesture pointed at, and the difference is the whole chain."""
    from agent_desk.web import blocks

    thread = await desk.create_thread("a chat")
    first = await desk.create_block(
        thread_id=thread.id, kind="question", input="combine them", thread_set_by="human"
    )
    await desk.finish_block(first.id, "steam, which neither water nor fire is")
    idea = await desk.create_idea(
        text_="fire", summary="fire", source_kind="typed", source_ref=None, context=None
    )

    look = await blocks.on_the_bench(
        desk, [], [f"answer:{first.id}", f"idea:{idea.id}"], [f"answer:{first.id}"]
    )

    assert [card.kind for card in look.cards] == ["answer", "idea"]
    assert "steam" in look.cards[0].said


async def test_an_exchange_the_message_only_carried_is_still_left_out(desk: Store) -> None:
    """The rule it was carved out of stays: the conversation is in the prompt as the thread, and a
    bench that lists it back has the model reasoning about the conversation as a thing on it."""
    from agent_desk.web import blocks

    thread = await desk.create_thread("a chat")
    first = await desk.create_block(
        thread_id=thread.id, kind="question", input="hello", thread_set_by="human"
    )
    await desk.finish_block(first.id, "hello back")

    look = await blocks.on_the_bench(desk, [], [f"answer:{first.id}"])

    assert look.cards == []


async def test_a_card_whose_exchange_is_gone_is_left_out(desk: Store) -> None:
    """A block can be deleted while its card is still on somebody's bench. Naming one is then a
    name and nothing behind it, and a card carrying an invented sentence is worse than one fewer
    card (CLAUDE.md, rule five)."""
    from agent_desk.web import blocks

    look = await blocks.on_the_bench(
        desk, [], ["answer:01M1NOSUCHBLOCK"], ["answer:01M1NOSUCHBLOCK"]
    )

    assert look.cards == []


async def test_a_named_card_with_nothing_written_on_it_is_not_invented(desk: Store) -> None:
    """A run that has not answered yet has no words, and a card carrying an empty sentence is the
    console saying something is there when nothing is (CLAUDE.md, rule five)."""
    from agent_desk.web import blocks

    thread = await desk.create_thread("a chat")
    first = await desk.create_block(
        thread_id=thread.id, kind="question", input="x", thread_set_by="human"
    )

    look = await blocks.on_the_bench(desk, [], [f"answer:{first.id}"], [f"answer:{first.id}"])

    assert look.cards == []


def test_the_gesture_names_them_all_the_way_down() -> None:
    """The route reads the pair once and hands it to both: the digest, so the model sees two cards,
    and the store, so the third card finds its way back under them after a reload."""
    route = (HERE / "agent_desk" / "web" / "routes.py").read_text(encoding="utf-8")

    assert "made_from=combined if len(combined) == 2 else ()" in route
    assert "await on_the_bench(store, rows, targets, made_from)" in (
        HERE / "agent_desk" / "web" / "blocks.py"
    ).read_text(encoding="utf-8")


def test_a_gesture_is_never_read_as_an_instruction() -> None:
    """Found in the browser, twice, and not hypothetically: a combine was read as `master` and the
    console started an agent in a worktree of its own. The words of a combine are written by the
    console, so there is nothing for a reader to work out — and dragging one card onto another must
    not be able to start work. The guard is here and not in the wording, because a prompt phrased
    more carefully is a prompt the next release of the classifier can read differently."""
    source = (HERE / "agent_desk" / "web" / "blocks.py").read_text(encoding="utf-8")

    assert '"question" if a_gesture else await classifier.kind(' in source
    assert "a_gesture=bool(made_from)," in source


async def test_a_gesture_never_reaches_the_classifier_at_all(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The source says `a_gesture`; this says what that buys. Reading a combine is not merely
    wasteful — `master` is the branch that starts an agent in a worktree, so the classifier must
    not see one at all."""
    from agent_desk.web import blocks

    read: list[str] = []
    landed: list[str] = []

    async def never(said: str, *, pointed_at: int = 0) -> str:
        read.append(said)
        return "master"

    async def answered(store: Store, block: object, rows: object, **rest: object) -> None:
        landed.append("answered")

    monkeypatch.setattr(blocks.classifier, "kind", never)
    monkeypatch.setattr(blocks, "_classify_and_answer", answered)

    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id,
        kind="question",
        input="Make one thing out of these two.",
        thread_set_by="human",
    )

    await blocks._work(desk, block, [], classify=False, a_gesture=True)

    assert read == [], "a drag was handed to the reader that decides whether to start an agent"
    assert landed == ["answered"]


async def test_a_typed_message_is_still_read(desk: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """The carve-out is for gestures and nothing else: a sentence somebody typed still has to be
    worked out, which is the whole of what the classifier is for."""
    from agent_desk.web import blocks

    read: list[str] = []

    async def reads(said: str, *, pointed_at: int = 0) -> str:
        read.append(said)
        return "idea"

    async def recorded(store: Store, block: object, rows: object) -> None:
        return None

    monkeypatch.setattr(blocks.classifier, "kind", reads)
    monkeypatch.setattr(blocks, "record_idea", recorded)

    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="a thought", thread_set_by="human"
    )

    await blocks._work(desk, block, [], classify=False)

    assert read == ["a thought"]
