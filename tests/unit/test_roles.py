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
