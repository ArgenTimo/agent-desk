"""Two holes in things that already worked (children of 01M1XC4Z1D2K…).

"Перечитаны закрытые идеи этой недели вместе с кодом, который их закрыл… Каждая из них работает;
ниже то, чего в них не хватает, чтобы ими можно было пользоваться дольше одного раза."

Both are the same shape of gap: an action that can be done and cannot be undone, or done in bulk
having been done once.
"""

from __future__ import annotations

import pathlib

import pytest

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


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


# --- every line at once (01M1XC4Z2Y4M…) ----------------------------------------------------------
@pytest.mark.unit
def test_a_card_s_lines_can_be_rubbed_out_together() -> None:
    """ "Когда карточка ошиблась ролью и обросла пятью неправильными связями, это пять нажатий и
    меню каждый раз.\" """
    assert "function rubOutLinesOf(" in _code()
    assert "rub out all ${linesOf(name).length} of its lines" in _code()


@pytest.mark.unit
def test_it_is_offered_only_when_there_is_more_than_one() -> None:
    """One line already has its own menu. A second way to do the same thing is a menu somebody has
    to choose between two identical entries in."""
    menu = _body("cardMenuFor")

    assert "linesOf(name).length > 1" in menu


@pytest.mark.unit
def test_only_the_lines_somebody_drew() -> None:
    """The ones this console works out for itself — which project a session is in, what a question
    went out with — are readings of facts, and rubbing one out would be rubbing out the fact. It
    is the rule the line's own menu already follows."""
    lines = _body("linesOf")

    assert "drawnTies" in lines
    assert "ownTies" not in lines, "the console's own readings are being offered for deletion"


@pytest.mark.unit
def test_only_the_lines_somebody_can_see() -> None:
    """A line is a statement about two cards rather than about a surface, so the same line shows on
    every bench holding both its ends — and a card here can be joined to a card on another chat's
    workbench.

    Measured in a browser: a card with two lines drawn on this bench offered to rub out three.
    Offering to remove something nobody can see is the mistake the undo had, and it is worse here
    because the count is on the button somebody is reading.
    """
    lines = _body("linesOf")

    assert "showing(line.from)" in lines and "showing(line.to)" in lines


# --- and a collection back into its cards (01M1XC4Z3697…) ----------------------------------------
@pytest.mark.unit
def test_a_collection_can_be_laid_back_out() -> None:
    """ "Группа, ушедшая в запрос, сворачивается в одну карточку — и разложить её обратно нельзя. А
    это ровно то, что захочется сделать, чтобы повторить вопрос с одной изменённой карточкой.\" """
    assert "async function layBackOut(" in _code()

    menu = _body("cardMenuFor")
    assert "classList.contains('collection')" in menu
    assert "lay it back out" in menu


@pytest.mark.unit
def test_the_collection_keeps_what_it_takes_to_put_a_card_back() -> None:
    """The row was a kind and a name, for reading. Putting a card back needs the same three things
    `pin` needs, so the list is the record *and* the way back rather than a description of one."""
    collecting = _body("collect")

    for field in ("row.dataset.kind", "row.dataset.id", "row.dataset.label"):
        assert field in collecting, f"a collected card does not record {field}"


@pytest.mark.unit
def test_a_card_already_on_the_bench_is_not_added_twice() -> None:
    """And the count says how many actually came back: "разложить обратно" over a bench that still
    has three of the five is two cards, and a message claiming five describes a different bench."""
    laying = _body("layBackOut")

    assert "if (surface.querySelector(" in laying and "continue" in laying
    assert "already on the workbench" in laying


@pytest.mark.unit
def test_the_cards_that_come_back_say_where_they_came_from() -> None:
    """045: a card on the bench answers "why is this here", and being laid back out of a group is
    one of the ways it can have got there."""
    assert "'laid back out of a group'" in _code()


# --- why the engine went that way (01M1XC4Z2F4C…) ------------------------------------------------
@pytest.mark.unit
def test_a_decision_records_what_decided_it() -> None:
    """ "Сейчас остаётся «пошёл туда-то». Не остаётся, на основании чего — а это ровно тот вопрос,
    который зададут, когда прогон пойдёт не туда.\" """
    from agent_desk.web import engine

    assert engine.read_branch("2 the tests came back red, so it cannot go out", 3) == 2
    assert engine.read_why("2 the tests came back red, so it cannot go out") == (
        "the tests came back red, so it cannot go out"
    )


@pytest.mark.unit
def test_the_number_still_has_to_come_first_and_alone() -> None:
    """Asking for a reason must not soften the reading of the branch. A process that took the
    first way out because the model said something conversational is the failure `read_branch`
    exists to refuse, and it refuses it exactly as before."""
    from agent_desk.web import engine

    assert engine.read_branch("I think option two", 3) == 0
    assert engine.read_branch("2 because", 1) == 0, "a number past the end is not a branch"


@pytest.mark.unit
def test_a_decision_with_no_reason_says_so_rather_than_inventing_one() -> None:
    """Absent is a real answer: it means the model did not give a reason, which is a different
    thing from a reason nobody wrote down. A made-up one beside a real branch would be
    indistinguishable from a real one — the worst possible place for a guess."""
    from agent_desk.web import engine

    assert engine.read_why("2") == ""
    assert engine.read_why("") == ""


@pytest.mark.unit
def test_the_reason_is_a_line_rather_than_an_essay() -> None:
    """It is read at a glance beside the branch it explains, on a card and in a run's history."""
    from agent_desk.web import engine

    assert len(engine.read_why("2 " + "x" * 500)) == engine.WHY_CHARS


@pytest.mark.unit
def test_the_prompt_asks_for_both_and_says_why_the_number_is_first() -> None:
    from agent_desk import process
    from agent_desk.web import engine

    card = process.Card(name="step:1", role="decision", label="ship it?", said={"ask": "ship?"})
    ways = [
        process.Line(from_name="step:1", to_name="step:2", kind="if", says="yes"),
        process.Line(from_name="step:1", to_name="step:3", kind="if", says="no"),
    ]

    said = engine.branch_prompt(card, ways)

    # The line wraps in the source, so the check is on the halves rather than on the join.
    assert "then a" in said and "few words saying what decided it" in said
    assert "why did it go that way" in said


# --- a template that has lost fields says so (01M1XC4Z32P4…) -------------------------------------
@pytest.mark.unit
async def test_a_template_names_the_fields_its_roles_no_longer_ask_for() -> None:
    """ "Поля, которых у роли больше нет, сейчас молча не записываются — это правильно, но человек
    об этом не узнаёт и получает карточку, которая выглядит заполненной.\" """
    import json
    import tempfile

    from agent_desk.store.repo import Store, TemplateStep
    from agent_desk.web import routes

    from tests.unit.test_kept_bench import _post_form

    with tempfile.TemporaryDirectory() as where:
        store = Store(pathlib.Path(where) / "agent-desk.db")
        await store.open()
        old_store, routes.store = routes.store, store
        try:
            await store.keep_template(
                name="a release",
                steps=[
                    TemplateStep(
                        ord=1,
                        role="action",
                        label="run the tests",
                        # One field the role asks for, and one it never did.
                        fields={"do": "run them", "how_loudly": "very"},
                        leave=(),
                    )
                ],
                lines=[],
            )

            _, body = await _post_form("/workbench/template/use", {"name": "a release"})
        finally:
            routes.store = old_store
            await store.close()

    said = json.loads(body)
    assert said["made"] is True
    assert said["lost"] == ["action · how_loudly"]


@pytest.mark.unit
async def test_a_field_nobody_filled_in_is_not_worth_a_sentence() -> None:
    """A field somebody left empty and a field that has since been removed are the same absence on
    the new card, and only one of them is news."""
    import json
    import tempfile

    from agent_desk.store.repo import Store, TemplateStep
    from agent_desk.web import routes

    from tests.unit.test_kept_bench import _post_form

    with tempfile.TemporaryDirectory() as where:
        store = Store(pathlib.Path(where) / "agent-desk.db")
        await store.open()
        old_store, routes.store = routes.store, store
        try:
            await store.keep_template(
                name="a release",
                steps=[
                    TemplateStep(
                        ord=1, role="action", label="run the tests", fields={"gone": "  "}, leave=()
                    )
                ],
                lines=[],
            )
            _, body = await _post_form("/workbench/template/use", {"name": "a release"})
        finally:
            routes.store = old_store
            await store.close()

    assert json.loads(body)["lost"] == []


@pytest.mark.unit
def test_the_page_says_it_rather_than_keeping_it() -> None:
    """A count returned and never shown is the same silence with extra steps."""
    assert "said.lost?.length" in _code()
    assert "no longer ask for" in _code()


# --- a decision can look at the world (01M1XC4Z2ADB…) --------------------------------------------
@pytest.mark.unit
def test_a_decision_is_told_what_the_steps_before_it_produced() -> None:
    """ "Развилка «прошёл ли гейт» сегодня отвечает по тому, что написано на карточке, — то есть по
    описанию, а не по факту."

    The branch after "run the tests" could not see what the tests said, which is the whole of what
    it was being asked about.
    """
    from agent_desk import process
    from agent_desk.web import engine

    card = process.Card(name="step:2", role="decision", label="did it pass?", said={"ask": "pass?"})
    ways = [process.Line(from_name="step:2", to_name="step:3", kind="if", says="yes")]

    said = engine.branch_prompt(card, ways, memory="What leads into this step:\n- Action: ran them")

    assert "What the steps before it produced" in said
    assert "ran them" in said


@pytest.mark.unit
def test_a_decision_is_told_what_the_console_has_read() -> None:
    """ "Решению нужен доступ к тому, что консоль и так знает: состояние задач, блокеры, результат
    прошлого шага." And told that these are readings rather than opinions — that instruction is
    the difference between giving a model facts and giving it atmosphere."""
    from agent_desk import process
    from agent_desk.web import engine

    card = process.Card(name="step:2", role="decision", label="ship?", said={"ask": "ship?"})
    ways = [process.Line(from_name="step:2", to_name="step:3", kind="if", says="yes")]

    said = engine.branch_prompt(card, ways, known=["- stopped: the gate said no"])

    assert "read off disk" in said
    assert "Facts, not opinions" in said
    assert "a decision that contradicts what is written here is" in said
    assert "the gate said no" in said


@pytest.mark.unit
async def test_what_is_known_is_about_this_project_and_bounded() -> None:
    """A decision about a release does not need to hear that another repository is stuck, and one
    drowned in context is one made on the first line of it."""
    import tempfile

    from agent_desk.store.repo import Store
    from agent_desk.web import engine

    with tempfile.TemporaryDirectory() as where:
        store = Store(pathlib.Path(where) / "agent-desk.db")
        await store.open()
        try:
            run = await store.start_run(cards=["step:1"], repo_key="mine", cwd="/tmp")
            for n in range(engine.THINGS_KNOWN + 4):
                task = await store.queue_task(
                    repo_key="mine",
                    instruction=f"a failure {n}",
                    cwd="/tmp",
                    title=f"a failure {n}",
                    source_kind="idea",
                )
                await store.task_started(task.id, f"agent{n}")
                await store.task_failed(task.id, "it broke")
            elsewhere = await store.queue_task(
                repo_key="somebody-else",
                instruction="not this project",
                cwd="/tmp",
                title="not this project",
                source_kind="idea",
            )
            await store.task_started(elsewhere.id, "other")
            await store.task_failed(elsewhere.id, "it broke")

            # And one that is still going, which is the other half of "состояние задач".
            await store.queue_task(
                repo_key="mine",
                instruction="still going",
                cwd="/tmp",
                title="still going",
                source_kind="idea",
            )
            # `take_next_task` is what marks a task as started; `task_started` only records which
            # agent took it. Going through the queue is also what a real run does.
            taken = await store.take_next_task("mine")
            assert taken is not None
            await store.task_started(taken.id, "agent-live")

            known = await engine._what_is_known(store, run)
        finally:
            await store.close()

    assert known, "a decision is told nothing at all"
    assert not [one for one in known if "not this project" in one]
    said = [one for one in known if "work that failed" in one]
    assert said, "no failure is mentioned at all, which a count-under-a-cap check would allow"
    assert len(said) <= engine.THINGS_KNOWN
    assert [one for one in known if "running right now" in one], (
        "a decision is not told what is in flight, which is half of what it was asked to see"
    )


# --- redrawing the drawing that is there (01M1XC4Z2SCT…) -----------------------------------------
@pytest.mark.unit
def test_a_description_can_redraw_the_process_on_the_bench() -> None:
    """ "«Слова → схема» умеет создавать новое и не умеет менять. Значит, поправить процесс словами
    нельзя — только собрать рядом второй и удалить первый.\" """
    console = _code()

    assert "data-redraw-sketch" in console
    assert "redrawSketch" in console

    board = (
        pathlib.Path(__file__).resolve().parents[2]
        / "agent_desk"
        / "web"
        / "templates"
        / "board.html"
    ).read_text(encoding="utf-8")
    assert "data-redraw-sketch" in board


@pytest.mark.unit
def test_redrawing_takes_off_the_steps_and_nothing_else() -> None:
    """Everything else on a workbench stands for something outside it — a session, an idea, a
    project — and taking one of those off because somebody rewrote a description would be losing
    something the description was never about."""
    steps = _body("stepsOnTheBench")

    assert "'.pin[data-kind=\"step\"]'" in steps


@pytest.mark.unit
def test_redrawing_is_offered_only_when_there_is_a_drawing_to_redraw() -> None:
    """On an empty bench the two buttons do the same thing under different words, which is a
    choice nobody can make."""
    console = _code()
    sketching = console[console.index("async function sketchFromWords(") :]
    sketching = sketching[: sketching.index("\n}\n")]

    assert "hidden = !stepsOnTheBench().length" in sketching


@pytest.mark.unit
async def test_the_reason_lands_on_the_card_and_in_the_run() -> None:
    """`read_why` is only half of it: the reason has to travel from the reply onto the card and
    into the run's history, which is where the question "why did it go that way" gets asked."""
    import tempfile

    from agent_desk import process
    from agent_desk.store.repo import Store
    from agent_desk.web import engine

    with tempfile.TemporaryDirectory() as where:
        store = Store(pathlib.Path(where) / "agent-desk.db")
        await store.open()
        try:
            run = await store.start_run(cards=["step:1"], repo_key="k", cwd="/tmp")
            card = process.Card(
                name="step:1", role="decision", label="ship?", said={"ask": "ship?"}
            )
            ways = [process.Line(from_name="step:1", to_name="step:2", kind="if", says="yes")]

            async def fake_ask(prompt: str) -> tuple[str, str]:
                return "1 the tests came back green", ""

            engine._ask, was = fake_ask, engine._ask  # type: ignore[assignment]
            try:
                await engine._decide(store, run, card, [card], ways)
            finally:
                engine._ask = was  # type: ignore[assignment]

            (step,) = await store.run_steps(run.id)
            made = (await store.cards_made())["step:1"]
        finally:
            await store.close()

    assert "went yes" in step.made
    assert "the tests came back green" in step.made
    assert "the tests came back green" in made, "the card does not carry the reason"
