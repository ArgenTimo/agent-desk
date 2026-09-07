"""A drawing said in words, and words read back as a drawing.

Two directions, and they are not the same kind of thing. One is a fact with one right answer and
no model call; the other is a guess, offered rather than applied. Most of what is asserted here is
that difference holding.
"""

from __future__ import annotations

import pytest
from agent_desk import process, telling


def card(name: str, role: str, label: str = "", **said: str) -> process.Card:
    return process.Card(name=name, role=role, label=label or name, said=said)


def line(one: str, other: str, kind: str = "then", says: str = "") -> process.Line:
    return process.Line(from_name=one, to_name=other, kind=kind, says=says)


@pytest.mark.unit
def test_a_drawing_reads_as_a_numbered_process() -> None:
    """ "Кто-то другой должен её понять, не открывая верстак." The order comes from the lines, the
    words from the fields, and turning one into the other has one right answer."""
    cards = [
        card("s:2", "action", "write it up", do="write up what was found"),
        card("s:1", "action", "read the logs", do="read the failing logs"),
    ]

    said = telling.as_words(cards, [line("s:1", "s:2")])

    assert said.splitlines()[0].startswith("1. read the failing logs")
    assert said.splitlines()[1].startswith("2. write up what was found")


@pytest.mark.unit
def test_the_ways_out_of_a_decision_are_listed_under_it_with_their_conditions() -> None:
    """A branch without its condition is a fork nobody can follow — in a diagram or in prose."""
    cards = [
        card("d:1", "decision", "is it real", ask="is this a real bug"),
        card("s:1", "action", "fix it", do="open a branch and fix it"),
        card("s:2", "action", "write it up", do="write it up and stop"),
    ]
    lines = [
        line("d:1", "s:1", "if", "it is a real bug"),
        line("d:1", "s:2", "if", "it is not"),
    ]

    said = telling.as_words(cards, lines)

    assert "Decide: is this a real bug." in said
    assert "If it is a real bug: fix it." in said
    assert "If it is not: write it up." in said


@pytest.mark.unit
def test_an_event_reads_as_waiting_and_a_trigger_reads_as_when() -> None:
    cards = [
        card("e:1", "event", "the release", awaits="the release goes out"),
        card("s:1", "action", "tell them", do="tell the team"),
    ]

    said = telling.as_words(cards, [line("e:1", "s:1", "when", "it goes out")])

    assert "Wait until the release goes out." in said
    assert "When it goes out: tell them." in said


@pytest.mark.unit
def test_a_thing_that_is_not_a_step_is_described_where_it_is_used() -> None:
    """ "The deploy log" on its own is not a line of a process — it is a thing one of the steps
    uses, and putting it in the numbered list would read as an instruction to do it."""
    cards = [
        card("o:1", "object", "the deploy log", what="yesterday's deploy log"),
        card("s:1", "action", "read it", do="read the failing logs"),
    ]

    said = telling.as_words(cards, [line("o:1", "s:1")])

    assert "1. read the failing logs" in said
    assert "2." not in said, "a thing that is not a step was numbered as one"
    assert "Using the deploy log (yesterday's deploy log)." in said


@pytest.mark.unit
def test_a_loop_is_said_out_loud_rather_than_left_out_of_the_description() -> None:
    """The part of a drawing that cannot be run is exactly the part a description must not omit."""
    cards = [card("s:1", "action", "one", do="one"), card("s:2", "action", "two", do="two")]

    said = telling.as_words(cards, [line("s:1", "s:2"), line("s:2", "s:1")])

    assert "loop" in said
    assert "one" in said and "two" in said


@pytest.mark.unit
def test_a_step_nobody_has_described_says_so_rather_than_reading_as_blank() -> None:
    cards = [card("s:1", "action", "a step")]

    assert "not yet described" in telling.as_words(cards, [])


@pytest.mark.unit
def test_an_empty_bench_says_nothing_at_all() -> None:
    assert telling.as_words([], []) == ""


@pytest.mark.unit
def test_a_shape_is_read_strictly_and_prose_about_a_shape_is_not_a_shape() -> None:
    """A model asked for a shape will sometimes answer with a paragraph about the shape, and a
    reader that accepted anything would put a drawing on somebody's bench that nobody described."""
    steps, lines = telling.read_shape(
        "Here is how I would draw that process, roughly speaking.\n"
        "It has three parts and the middle one is a decision.\n"
    )

    assert steps == []
    assert lines == []


@pytest.mark.unit
def test_a_shape_that_is_a_shape_is_read() -> None:
    steps, lines = telling.read_shape(
        "action | read the logs | read yesterday's failing logs\n"
        "decision | is it real | is this a real bug\n"
        "action | fix it | open a branch and fix it\n"
        "1 -> 2 : then :\n"
        "2 -> 3 : if : it is a real bug\n"
    )

    assert [one["role"] for one in steps] == ["action", "decision", "action"]
    assert steps[0]["label"] == "read the logs"
    assert steps[0]["words"] == "read yesterday's failing logs"
    assert lines == [
        {"from": "1", "to": "2", "kind": "then", "says": ""},
        {"from": "2", "to": "3", "kind": "if", "says": "it is a real bug"},
    ]


@pytest.mark.unit
def test_a_line_pointing_at_a_step_that_is_not_there_is_dropped() -> None:
    """A drawing with a dangling arrow is harder to correct than one with none."""
    steps, lines = telling.read_shape("action | one | do one\n1 -> 4 : then :\n1 -> 1 : then :\n")

    assert len(steps) == 1
    assert lines == [{"from": "1", "to": "1", "kind": "then", "says": ""}]


@pytest.mark.unit
def test_a_line_of_a_kind_this_program_does_not_have_is_dropped() -> None:
    steps, lines = telling.read_shape(
        "action | one | do one\naction | two | do two\n1 -> 2 : leads-towards : \n"
    )

    assert len(steps) == 2
    assert lines == []


@pytest.mark.unit
def test_a_role_this_program_does_not_have_is_not_a_step() -> None:
    steps, _ = telling.read_shape("gizmo | one | do one\naction | two | do two\n")

    assert [one["label"] for one in steps] == ["two"]


@pytest.mark.unit
def test_the_prompt_says_not_to_invent_steps() -> None:
    """A model asked to draw a process will happily add the two steps everybody's process has, and
    a person accepting the proposal would be accepting work they never described."""
    asked = telling.shape_prompt("read the logs, then write it up")

    assert "Do not invent steps" in asked
    assert "read the logs, then write it up" in asked
    for role in ("object", "action", "decision", "event", "result"):
        assert role in asked
    for kind in ("then", "if", "when", "makes", "with"):
        assert kind in asked


@pytest.mark.unit
def test_a_proposed_step_s_words_go_into_the_field_its_role_actually_needs() -> None:
    """A proposal that put the description somewhere the role does not ask about would produce
    cards that look filled in and read as empty to everything else."""
    assert telling.words_for("action") == "do"
    assert telling.words_for("decision") == "ask"
    assert telling.words_for("event") == "awaits"
    assert telling.words_for("result") == "counts"
    # An Object needs nothing, so its one field is where the words go.
    assert telling.words_for("object") == "what"
    assert telling.words_for("not a role") == ""


@pytest.mark.unit
def test_a_line_is_read_before_any_numbering_is_stripped_off_it() -> None:
    """A line begins with the number of the step it leaves. Stripping leading digits to tidy up a
    numbered list of steps turned every line into unparseable rubbish — and silently, because a
    line that does not parse is skipped by design.
    """
    _, lines = telling.read_shape(
        "action | one | do one\naction | two | do two\n1 -> 2 : then : straight after\n"
    )

    assert lines == [{"from": "1", "to": "2", "kind": "then", "says": "straight after"}]


@pytest.mark.unit
def test_a_step_that_arrives_numbered_is_still_a_step() -> None:
    """Which is what the stripping was there for in the first place."""
    steps, _ = telling.read_shape("1. action | one | do one\n2) action | two | do two\n")

    assert [one["label"] for one in steps] == ["one", "two"]


# --- and the routes behind them -----------------------------------------------------------------

import pathlib  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402

from agent_desk.store.repo import Store  # noqa: E402
from agent_desk.web import routes  # noqa: E402


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


@pytest.mark.unit
async def test_the_route_says_the_drawing_in_words_without_asking_anything(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No model call: the order comes from the lines and the words from the fields. A description
    that came back differently on two afternoons would be no use for handing work to somebody."""

    def never(*args: object, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("saying a drawing in words asked a model")

    monkeypatch.setattr(routes.answer_session, "stream_answer", never)
    one = await desk.add_step_card("read the logs")
    two = await desk.add_step_card("write it up")
    await desk.set_card_field(one.name, "do", "read yesterday's failing logs")
    await desk.set_card_field(two.name, "do", "write up what was found")
    await desk.tie_cards(from_name=one.name, to_name=two.name, kind="then")

    answer = await routes.workbench_words(cards=f"{two.name},{one.name}")
    body = bytes(answer.body).decode()

    assert "read yesterday's failing logs" in body
    assert body.index("read yesterday") < body.index("write up what was found")


@pytest.mark.unit
async def test_a_sketch_is_offered_and_nothing_reaches_the_bench_until_somebody_presses(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A machine may propose, a person disposes — the same rule the meeting intake and the whole
    idea pool follow."""

    async def answered(prompt: str, **kwargs: object) -> AsyncIterator[str]:
        yield "action | read the logs | read the failing logs\n"
        yield "action | write it up | write up what was found\n"
        yield "1 -> 2 : then :\n"

    monkeypatch.setattr(routes.answer_session, "stream_answer", answered)
    from tests.unit.test_input import _post

    status, body, _ = await _post("/workbench/sketch", {"words": "read the logs then write it up"})

    assert status == 200
    assert "read the failing logs" in body
    # Nothing has been made.
    assert await desk.step_cards() == []
    assert await desk.card_ties() == []


@pytest.mark.unit
async def test_a_sketch_that_is_pressed_becomes_cards_and_lines(desk: Store) -> None:
    from tests.unit.test_input import _post

    await _post(
        "/workbench/sketch/keep",
        {
            "steps": "action|read the logs|read the failing logs\n"
            "decision|is it real|is this a real bug",
            "lines": "1|2|then|",
        },
    )

    made = await desk.step_cards()
    assert len(made) == 2
    roles_now = await desk.card_roles()
    assert set(roles_now.values()) == {"action", "decision"}
    fields = await desk.card_fields()
    assert any(one.get("do") == "read the failing logs" for one in fields.values())
    assert any(one.get("ask") == "is this a real bug" for one in fields.values())
    assert len(await desk.card_ties()) == 1


@pytest.mark.unit
async def test_a_sketch_with_a_role_this_program_does_not_have_makes_no_card(desk: Store) -> None:
    """The proposal is read by a person and then posted back by a page. Neither is a promise about
    what is in the body."""
    from tests.unit.test_input import _post

    await _post("/workbench/sketch/keep", {"steps": "gizmo|one|do one", "lines": ""})

    assert await desk.step_cards() == []


@pytest.mark.unit
async def test_a_description_that_could_not_be_read_says_so_rather_than_drawing_nothing(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def waffled(prompt: str, **kwargs: object) -> AsyncIterator[str]:
        yield "Well, it rather depends on what you mean by a process.\n"

    monkeypatch.setattr(routes.answer_session, "stream_answer", waffled)
    from tests.unit.test_input import _post

    status, body, _ = await _post("/workbench/sketch", {"words": "something"})

    assert status == 422
    assert "could read" in body


@pytest.mark.unit
async def test_an_empty_description_is_refused_before_anything_is_asked(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*args: object, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("an empty description was sent to a model")

    monkeypatch.setattr(routes.answer_session, "stream_answer", never)
    from tests.unit.test_input import _post

    status, _, _ = await _post("/workbench/sketch", {"words": "   "})

    assert status == 400


@pytest.mark.unit
async def test_an_answer_engine_that_is_not_there_is_reported_rather_than_raised(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def gone(prompt: str, **kwargs: object) -> AsyncIterator[str]:
        raise OSError("no such binary")
        yield ""  # pragma: no cover

    monkeypatch.setattr(routes.answer_session, "stream_answer", gone)
    from tests.unit.test_input import _post

    status, body, _ = await _post("/workbench/sketch", {"words": "anything"})

    assert status == 502
    assert "no such binary" in body


@pytest.mark.unit
async def test_a_step_card_is_made_named_and_rendered(desk: Store) -> None:
    from tests.unit.test_input import _post

    status, body, _ = await _post("/cards/step", {"label": "read the logs", "role": "action"})
    assert status == 200
    (made,) = await desk.step_cards()
    assert made.label == "read the logs"
    assert (await desk.card_roles())[made.name] == "action"

    await _post("/cards/step/name", {"id": made.id, "label": "read the older logs"})
    assert (await desk.step_card(made.id)).label == "read the older logs"  # type: ignore[union-attr]

    shown = await routes.card("step", made.id)
    assert shown.status_code == 200
    assert "read the older logs" in bytes(shown.body).decode()

    missing = await routes.card("step", "nothing")
    assert missing.status_code == 404


@pytest.mark.unit
async def test_saving_a_process_needs_a_name_and_some_cards(desk: Store) -> None:
    from tests.unit.test_input import _post

    status, _, _ = await _post("/workbench/template", {"name": "", "cards": "step:1"})
    assert status == 400

    made = await desk.add_step_card("one")
    await desk.set_card_field(made.name, "do", "do one")
    status, body, _ = await _post(
        "/workbench/template", {"name": "the release", "cards": made.name}
    )
    assert status == 200

    (kept,) = await desk.templates()
    assert kept.name == "the release"
    assert kept.steps[0].fields == {"do": "do one"}

    listed = await routes.list_templates()
    assert "the release" in bytes(listed.body).decode()


@pytest.mark.unit
async def test_using_a_process_that_is_not_there_says_so(desk: Store) -> None:
    from tests.unit.test_input import _post

    status, body, _ = await _post("/workbench/template/use", {"name": "nothing"})

    assert status == 404
    assert "no template" in body
