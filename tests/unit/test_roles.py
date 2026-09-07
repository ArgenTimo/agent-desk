"""What a card is in a process, as opposed to where it came from.

The first user's feedback asked for five card types and for a card to be able to change type as a
process is described. Both halves are here: the vocabulary, and the reason it cannot be the `kind`
field that already exists.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import roles
from agent_desk.store.repo import Store
from agent_desk.web import routes


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


@pytest.mark.unit
def test_the_five_are_the_five_that_were_asked_for() -> None:
    """ "Object (что-то существует), Action (что-то сделать), Decision (выбрать / проверить
    условие), Event (что-то произошло), Result (что-то получилось)."

    Five, and the number matters more than it looks: it is what every process notation converges
    on because they are the distinctions you cannot describe work without. A sixth is a taxonomy
    somebody has to learn.
    """
    assert set(roles.ROLES) == {"object", "action", "decision", "event", "result"}
    for one in roles.ROLES.values():
        assert one.says and one.means and one.shape


@pytest.mark.unit
def test_every_role_is_a_different_silhouette() -> None:
    """Drawn as shape rather than colour, because on this page colour means status and nothing
    else — and because shape is what was actually asked for: a diamond reads as a decision before
    the text inside it is read. Two roles sharing a shape is two roles you cannot tell apart."""
    shapes = [one.shape for one in roles.ROLES.values()]

    assert len(set(shapes)) == len(shapes), f"two roles look the same: {shapes}"


@pytest.mark.unit
def test_a_card_nobody_has_typed_has_the_role_its_kind_already_is() -> None:
    """Asking somebody to type five cards before they can draw one line is how a constructor goes
    unused. The defaults are readings of what each kind already is, not predictions about it."""
    assert roles.role_of("session").name == "action"
    assert roles.role_of("blocker").name == "event"
    assert roles.role_of("idea").name == "object"
    assert roles.role_of("group").name == "result"


@pytest.mark.unit
def test_a_kind_this_program_does_not_know_is_still_something_that_exists() -> None:
    """A card on the bench is at least a thing that exists, and leaving it untyped would put a
    hole in a diagram whose whole value is that every box says what it is."""
    assert roles.role_of("something-new").name == "object"


@pytest.mark.unit
def test_a_card_can_be_given_a_role_its_kind_is_not() -> None:
    """ "Карточка может менять тип по ходу процесса." This is the whole reason the role is a
    separate field: an idea does not become a session, but it can perfectly well be the Result of
    a step, and reusing `kind` would have made that unsayable."""
    assert roles.role_of("idea", "result").name == "result"
    assert roles.role_of("session", "decision").name == "decision"


@pytest.mark.unit
def test_a_role_that_no_longer_exists_renders_as_the_natural_one(caplog: object) -> None:
    """Roles are written by a page and read back later. A name that has since been removed from
    the five must render as the card's natural role — not raise on somebody's board."""
    assert roles.role_of("idea", "whatever-this-was").name == "object"


@pytest.mark.unit
async def test_a_chosen_role_is_kept_and_can_be_taken_back(desk: Store) -> None:
    """Taking it back stores no row at all: absent means "whatever this kind naturally is", which
    is a different thing from a role somebody chose and then emptied."""
    await desk.set_card_role("idea:one", "result")
    assert await desk.card_roles() == {"idea:one": "result"}

    await desk.set_card_role("idea:one", "")
    assert await desk.card_roles() == {}


@pytest.mark.unit
async def test_the_route_takes_the_five_and_nothing_else(desk: Store) -> None:
    """The point of five is that a diagram can be read without reading it, and a sixth name typed
    into a form is how that becomes a free-text label with a shape attached."""
    from tests.unit.test_input import _post

    await _post("/cards/role", {"name": "idea:one", "role": "decision"}, htmx=True)
    assert await desk.card_roles() == {"idea:one": "decision"}

    await _post("/cards/role", {"name": "idea:one", "role": "a shape I invented"}, htmx=True)
    assert await desk.card_roles() == {"idea:one": "decision"}, "an invented role was stored"

    await _post("/cards/role", {"name": "idea:one", "role": ""}, htmx=True)
    assert await desk.card_roles() == {}


@pytest.mark.unit
async def test_the_page_is_told_the_five_rather_than_carrying_its_own_copy(desk: Store) -> None:
    """A list of them written into the script or the stylesheet would be a second place for them
    to be wrong, and the one that goes wrong silently."""
    await desk.set_card_role("idea:one", "event")

    answer = await routes.card_roles()
    body = bytes(answer.body).decode()

    assert answer.status_code == 200
    assert "idea:one" in body and "event" in body
    for name in roles.ROLES:
        assert name in body
    assert "session" in body, "the page is not told what a kind naturally is"


@pytest.mark.unit
def test_the_console_asks_for_the_five_rather_than_listing_them() -> None:
    static = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"
    console = (static / "console.js").read_text(encoding="utf-8")

    assert "'/cards/roles'" in console
    for name in ("object", "action", "decision", "event", "result"):
        # `object` and `action` appear in ordinary JavaScript prose, so this checks for the shape
        # of a hardcoded list rather than for the words.
        assert f"'{name}', '" not in console, "the five are listed in the page as well"


@pytest.mark.unit
def test_every_role_asks_a_small_fixed_set_and_no_role_asks_nothing() -> None:
    """ "Набор маленький и фиксированный на тип: поле, которое можно назвать как угодно, — это
    снова свободный текст, а свободный текст движок исполнить не может."

    Small on purpose: three fields is a form somebody fills in, six is a form somebody abandons.
    A role that asks nothing is a role that cannot be executed and probably should not exist.
    """
    for name in roles.ROLES:
        asked = roles.fields_of(name)
        assert asked, f"{name} asks nothing about itself"
        assert len(asked) <= 3, f"{name} asks {len(asked)} things, which is a form nobody fills in"
        assert len({field.name for field in asked}) == len(asked), f"{name} asks the same twice"


@pytest.mark.unit
def test_a_decision_keeps_its_branches_on_the_lines_and_not_in_a_field() -> None:
    """They live on the `if` lines going out of it, because that is where somebody draws them. A
    "branches" field on the card would be the same information written twice, wrong from the
    moment the two disagree."""
    asked = {field.name for field in roles.fields_of("decision")}

    assert "branches" not in asked and "ways" not in asked
    assert asked == {"ask"}


@pytest.mark.unit
def test_every_role_but_object_has_something_it_cannot_run_without() -> None:
    """An Object is a thing that exists — it can be a card with a name and nothing else, which is
    most of what people put on a bench. The other four are steps, and a step that has not said
    what it does is a step an engine has to stop on."""
    assert not any(field.needed for field in roles.fields_of("object"))
    for name in ("action", "decision", "event", "result"):
        assert any(field.needed for field in roles.fields_of(name)), f"{name} needs nothing"


@pytest.mark.unit
def test_what_is_still_missing_is_reported_and_not_refused() -> None:
    """A diagram half-drawn is a diagram being thought about. This is what an engine would have to
    stop on, which is why it is worth showing on the card first."""
    assert roles.missing("action", {}) == ("what to do",)
    assert roles.missing("action", {"do": "   "}) == ("what to do",), "whitespace is not an answer"
    assert roles.missing("action", {"do": "run the gate"}) == ()
    assert roles.missing("object", {}) == ()


@pytest.mark.unit
def test_only_a_field_the_role_actually_has_can_be_written() -> None:
    """The whole difference between this and a notes table with a key on it."""
    assert roles.is_a_field("action", "do")
    assert not roles.is_a_field("action", "whatever I feel like")
    assert not roles.is_a_field("object", "do"), "a field leaked across roles"
    assert not roles.is_a_field("a role that does not exist", "do")


@pytest.mark.unit
async def test_a_field_is_kept_and_clearing_it_leaves_no_row(desk: Store) -> None:
    """ "Nobody has answered this" and "somebody answered it with nothing" are the same state, and
    keeping two ways to say it would mean `missing` had to know about both."""
    await desk.set_card_field("idea:one", "do", "run the gate")
    assert await desk.card_fields() == {"idea:one": {"do": "run the gate"}}

    await desk.set_card_field("idea:one", "do", "  ")
    assert await desk.card_fields() == {}


@pytest.mark.unit
async def test_words_survive_a_card_changing_its_role_and_changing_back(desk: Store) -> None:
    """ "Карточка может менять тип по ходу процесса" — and losing what somebody typed on every
    change would make that expensive rather than free."""
    await desk.set_card_role("idea:one", "action")
    await desk.set_card_field("idea:one", "do", "run the gate")

    await desk.set_card_role("idea:one", "result")
    await desk.set_card_role("idea:one", "action")

    assert (await desk.card_fields())["idea:one"]["do"] == "run the gate"


@pytest.mark.unit
async def test_the_route_refuses_a_field_the_role_does_not_have(desk: Store) -> None:
    from tests.unit.test_input import _post

    status, _, _ = await _post(
        "/cards/field", {"name": "idea:one", "role": "action", "field": "do", "value": "the work"}
    )
    assert status == 200

    status, _, _ = await _post(
        "/cards/field",
        {"name": "idea:one", "role": "action", "field": "invented", "value": "anything"},
    )
    assert status == 400

    # And a field that belongs to a *different* role is refused too, which is the case a check on
    # "is this a known field name anywhere" would let through.
    status, _, _ = await _post(
        "/cards/field", {"name": "idea:one", "role": "object", "field": "do", "value": "the work"}
    )
    assert status == 400

    assert await desk.card_fields() == {"idea:one": {"do": "the work"}}


@pytest.mark.unit
async def test_the_page_is_told_what_each_role_asks(desk: Store) -> None:
    """A field the page knows about and the store does not is a field that silently fails to
    save — which is worse than either of them not having it."""
    await desk.set_card_field("idea:one", "ask", "did the gate pass")

    answer = await routes.card_roles()
    body = bytes(answer.body).decode()

    assert '"fields"' in body
    assert "what to do" in body and "what to check" in body
    assert "did the gate pass" in body, "what is already typed is not sent with the definitions"


@pytest.mark.unit
def test_the_form_is_drawn_from_what_the_role_asks_rather_than_per_card_template() -> None:
    """Any card can have any role, so a form in the session template would have to be copied into
    the idea, blocker and folder templates — three of which would fall behind the fourth."""
    static = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"
    console = (static / "console.js").read_text(encoding="utf-8")

    assert "function showFields(" in console
    drawn = console[console.index("function showFields(") :]
    drawn = drawn[: drawn.index("\n}\n")]
    assert "roleSays[role]?.fields" in console
    assert "form.dataset.role === role" in drawn, (
        "the form is rebuilt on every pass, which takes the caret out of an input somebody is "
        "typing in — the worst thing a form on a live-updating page can do"
    )
