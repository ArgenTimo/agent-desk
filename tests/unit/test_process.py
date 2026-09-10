"""A bench of typed cards and typed lines, read as a process.

"Result одного шага должен быть входом для следующего, иначе схема из пяти блоков — это пять
независимых запросов." Everything here is pure: the order, what feeds what, and what a step gets
told are functions of the drawing, so they can be checked without starting anything.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import process


def card(name: str, role: str, **said: str) -> process.Card:
    made = said.pop("made", "")
    return process.Card(name=name, role=role, label=name, said=said, made=made)


def line(one: str, other: str, kind: str = "then") -> process.Line:
    return process.Line(from_name=one, to_name=other, kind=kind)


@pytest.mark.unit
def test_the_order_is_the_order_the_lines_describe() -> None:
    cards = [card("a:3", "action"), card("a:1", "action"), card("a:2", "action")]
    lines = [line("a:1", "a:2"), line("a:2", "a:3")]

    walked = process.order(cards, lines)

    assert walked.steps == ("a:1", "a:2", "a:3")
    assert walked.tangled == ()


@pytest.mark.unit
def test_two_steps_that_could_equally_go_first_come_out_in_the_order_they_were_given() -> None:
    """A process that runs in a different order on two identical benches is a process nobody can
    reason about — and a set iterating differently between two runs is exactly how that happens."""
    cards = [card("a:1", "action"), card("a:2", "action"), card("a:3", "action")]
    lines = [line("a:1", "a:3"), line("a:2", "a:3")]

    assert process.order(cards, lines).steps == ("a:1", "a:2", "a:3")
    # And the same drawing described in the other order says the other order, rather than one of
    # them silently winning both times.
    flipped = [card("a:2", "action"), card("a:1", "action"), card("a:3", "action")]
    assert process.order(flipped, lines).steps == ("a:2", "a:1", "a:3")


@pytest.mark.unit
def test_a_card_with_no_lines_on_it_still_runs() -> None:
    """The ordinary state of a process somebody has just started drawing."""
    walked = process.order([card("a:1", "action")], [])

    assert walked.steps == ("a:1",)


@pytest.mark.unit
def test_a_loop_is_named_rather_than_guessed_at() -> None:
    """A person drawing a process will draw a loop, on purpose and by accident. A step in a cycle
    has no "before", and inventing one produces a run whose order nobody chose."""
    cards = [card("a:1", "action"), card("a:2", "action"), card("a:3", "action")]
    lines = [line("a:1", "a:2"), line("a:2", "a:3"), line("a:3", "a:2")]

    walked = process.order(cards, lines)

    assert walked.steps == ("a:1",)
    assert set(walked.tangled) == {"a:2", "a:3"}
    assert not walked.runnable


@pytest.mark.unit
def test_a_line_that_says_only_related_does_not_feed_anything() -> None:
    """`with` says two things are related in no particular order. Treating it as a feed would put
    every loosely-associated card on the bench into every step's input, which is how a context
    window fills up with things nobody meant."""
    cards = [card("o:1", "object"), card("a:1", "action")]

    assert process.feeding("a:1", cards, [line("o:1", "a:1", "with")]) == ()
    assert [one.name for one in process.feeding("a:1", cards, [line("o:1", "a:1", "then")])] == [
        "o:1"
    ]


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["then", "if", "when", "makes"])
def test_every_line_that_says_something_happens_carries_something_in(kind: str) -> None:
    cards = [card("o:1", "object"), card("a:1", "action")]

    assert process.feeding("a:1", cards, [line("o:1", "a:1", kind)])


@pytest.mark.unit
def test_a_step_is_told_what_leads_directly_into_it_and_not_the_whole_ancestry() -> None:
    """Carrying the entire graph would put the first card of a twelve-step process into the
    briefing of the last. What the earlier steps contributed arrives through what the step in
    between *made*, which is the point of keeping a result at all."""
    cards = [
        card("a:1", "action", do="read the logs"),
        card("a:2", "action", do="fix it"),
        card("a:3", "action", do="write it up"),
    ]
    lines = [line("a:1", "a:2"), line("a:2", "a:3")]

    said = process.memory_for("a:3", cards, lines)

    assert "fix it" in said
    assert "read the logs" not in said


@pytest.mark.unit
def test_what_a_step_produced_is_told_apart_from_what_it_was_asked_to_do() -> None:
    """A step that has run is a fact; a step that has only been described is a plan. A briefing
    presenting the two identically would let an agent act on a result that does not exist yet."""
    cards = [
        process.Card(
            name="a:1", role="action", label="fix it", said={"do": "fix it"}, made="fixed in b1f3"
        ),
        card("a:2", "action", do="write it up"),
    ]

    said = process.memory_for("a:2", cards, [line("a:1", "a:2")])

    assert "what it produced: fixed in b1f3" in said
    assert said.index("fix it") < said.index("fixed in b1f3")


@pytest.mark.unit
def test_a_step_with_nothing_leading_into_it_is_told_nothing() -> None:
    """Rather than an empty heading, which reads as "there was something and it is missing"."""
    assert process.memory_for("a:1", [card("a:1", "action", do="go")], []) == ""


@pytest.mark.unit
def test_what_is_still_missing_is_gathered_before_a_run_rather_than_during_one() -> None:
    """Discovering it halfway through, with three agents already going, is the failure."""
    cards = [card("a:1", "action"), card("a:2", "action", do="go"), card("o:1", "object")]

    assert process.unfinished(cards) == {"a:1": ("what to do",)}


@pytest.mark.unit
def test_why_a_drawing_cannot_be_run_has_one_answer() -> None:
    """One function, so that whatever offers the button and whatever refuses the run agree — the
    same argument as autostart.why_not."""
    assert "nothing here is a step" in process.ready_to_run([card("o:1", "object")], [])

    loop = [card("a:1", "action", do="go"), card("a:2", "action", do="go")]
    assert "loop" in process.ready_to_run(loop, [line("a:1", "a:2"), line("a:2", "a:1")])

    assert "have not said what they need" in process.ready_to_run([card("a:1", "action")], [])
    assert process.ready_to_run([card("a:1", "action", do="go")], []) == ""


@pytest.mark.unit
def test_only_the_three_that_do_something_are_steps() -> None:
    """An Object is a thing that exists and a Result is what came out. Neither is executed; both
    are read by the steps around them."""
    assert set(process.STEPS) == {"action", "decision", "event"}


@pytest.mark.unit
def test_a_permission_and_a_step_are_the_same_idea_of_step() -> None:
    """The chip on a card and the reader that orders them must agree about what a step is, or a
    card gets permissions it is never asked about — or is run with none.

    They used to agree by both listing the five roles, and this test compared the two lists. They
    now agree by construction: the page asks whether the server said anything about *this card's*
    permissions, and the server answers that for `process.STEPS` and nothing else. One list, and
    the page has none — which is what `test_roles` asks of every other vocabulary here.
    """
    console = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
    ).read_text(encoding="utf-8")

    shown = console[console.index("function showLeave(") :]
    shown = shown[: shown.index("\n}\n")]
    assert "isAStep(pin)" in shown, "the permissions chip decides for itself what a step is"
    for role in (*process.STEPS, "object", "result"):
        assert f"'{role}'" not in shown, f"{role} is named in the page as well"

    asking = console[console.index("function isAStep(") :]
    asking = asking[: asking.index("\n}\n")]
    assert "processSaid.leave" in asking, "it does not ask what the server said about steps"

    # And the server answers it for the steps and for nothing else, which is the other half.
    routes = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "routes.py"
    ).read_text(encoding="utf-8")
    served = routes[routes.index('"leave": {') :]
    assert "card.role in process.STEPS" in served[: served.index("},")]


@pytest.mark.unit
def test_the_order_does_not_depend_on_the_order_the_lines_were_drawn() -> None:
    """The tie above is broken by where the cards sit, which is what somebody arranged. The lines
    must not get a vote — and they are the ones most likely to try.

    `store.card_ties()` hands them back ordered by the names at their ends, which is an ordering by
    id: arbitrary, and it changes as soon as somebody redraws one. A run whose steps came out in a
    different order because a line was rubbed out and drawn again would be a drawing nobody can
    compare against yesterday's (agent_desk/spread.py reads runs step by step).
    """
    import itertools

    cards = [
        card("a:1", "action"),
        card("a:2", "action"),
        card("a:3", "action"),
        card("a:4", "action"),
    ]
    lines = [line("a:1", "a:2"), line("a:2", "a:4"), line("a:1", "a:3"), line("a:3", "a:4")]

    orders = {
        process.order(cards, list(shuffled)).steps for shuffled in itertools.permutations(lines)
    }

    assert orders == {("a:1", "a:2", "a:3", "a:4")}


@pytest.mark.unit
def test_the_same_drawing_gives_the_same_order_every_time() -> None:
    """Said out loud because the failure it guards is invisible: a `set` somewhere in here would
    pass every test that asks once."""
    cards = [card("a:1", "action"), card("a:2", "action"), card("a:3", "action")]
    lines = [line("a:1", "a:2"), line("a:1", "a:3")]

    once = process.order(cards, lines).steps

    assert all(process.order(cards, lines).steps == once for _ in range(50))


@pytest.mark.unit
def test_a_line_to_a_card_that_is_not_here_orders_what_is() -> None:
    """A bench is a surface somebody arranges, and a line is a statement about two cards rather
    than about a surface: dragging one end off leaves the line pointing at something not here."""
    said = process.order([card("a:1", "action")], [line("a:1", "a:gone")])

    assert said.steps == ("a:1",)
    assert said.tangled == ()


@pytest.mark.unit
@pytest.mark.parametrize("shape", ["deep", "wide"])
def test_a_drawing_far_larger_than_anybody_draws_still_orders(shape: str) -> None:
    """Three hundred steps is not a drawing anybody makes by hand — it is what "put a saved
    workbench back" twice, or a template used on a full bench, can produce. A recursive walk would
    meet the interpreter's limit at a few hundred and take the console down with it.
    """
    many = 300
    cards = [card(f"a:{n}", "action") for n in range(many)]
    lines = (
        [line(f"a:{n}", f"a:{n + 1}") for n in range(many - 1)]
        if shape == "deep"
        else [line("a:0", f"a:{n}") for n in range(1, many)]
    )

    said = process.order(cards, lines)

    assert len(said.steps) == many
    assert said.tangled == ()
