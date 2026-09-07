"""Ideas somebody wrote, and ideas this console suggested.

"Моя-твоя — некорректное описание, скорее идея, в контекст которой я погружён или нет. Когда я
пишу идею, я буквально вынимаю её из контекста своего мозга, но когда ты её генерируешь, мне её
ещё необходимо осознать и понять."

That framing is what these assert. The column is not about credit: an idea a person wrote arrives
with the context it grew out of already in their head; one this console proposed arrives without
it, and everything here is about getting that context to them before anything is built.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.ideas import inbox
from agent_desk.store.repo import Store
from agent_desk.web import routes

KEY = "origin:acme/api"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


@pytest.mark.unit
async def test_an_idea_is_the_persons_own_unless_it_says_otherwise(desk: Store) -> None:
    """Every idea written before this column existed was typed by a person, and a default that
    guessed otherwise would put a hundred and eighty of them behind an approval nobody asked for.
    """
    mine = await inbox.capture(desk, "cache the probe results", project_key=KEY)

    assert mine.author == "human"
    assert not mine.proposed
    assert (await desk.idea(mine.id)).author == "human"  # type: ignore[union-attr]


@pytest.mark.unit
async def test_a_proposal_is_waiting_to_be_looked_at_rather_than_waiting_to_be_done(
    desk: Store,
) -> None:
    theirs = await inbox.capture(desk, "the folder cards could name their files", author="desk")

    assert theirs.proposed
    # Approving it is what `kept` already means. It stops asking the moment somebody says yes.
    await desk.set_idea_state(theirs.id, "kept")
    again = await desk.idea(theirs.id)
    assert again is not None
    assert again.author == "desk"
    assert not again.proposed, "an approved proposal is still asking to be approved"


@pytest.mark.unit
async def test_nothing_is_built_from_a_proposal_nobody_has_approved(desk: Store) -> None:
    """The difference between "I wrote this down" and "something suggested this to me" is exactly
    that the second has not been agreed to — and this console may start agents on its own, so an
    unapproved proposal reaching the queue would be it deciding what to build."""
    theirs = await inbox.capture(
        desk, "the folder cards could name their files", project_key=KEY, author="desk"
    )
    mine = await inbox.capture(desk, "cache the probe results", project_key=KEY)

    html = await routes.render_ideas()

    assert f"/ideas/{mine.id}/build" in html
    assert f"/ideas/{theirs.id}/build" not in html, "a proposal nobody approved offers to be built"
    assert "I approve this" in html
    assert "Set it aside" in html


@pytest.mark.unit
async def test_an_approved_proposal_can_then_be_built(desk: Store) -> None:
    theirs = await inbox.capture(desk, "a proposal", project_key=KEY, author="desk")
    await desk.set_idea_state(theirs.id, "kept")

    html = await routes.render_ideas()

    assert f"/ideas/{theirs.id}/build" in html


@pytest.mark.unit
async def test_where_an_idea_came_from_is_marked_without_recolouring_its_state(
    desk: Store,
) -> None:
    """On this page colour means status and nothing else, and that rule is older and worth more
    than this feature. A proposal is marked by its own label and its own ground."""
    await inbox.capture(desk, "a proposal", project_key=KEY, author="desk")

    html = await routes.render_ideas()
    css = (
        pathlib.Path(__file__).resolve().parents[2]
        / "agent_desk"
        / "web"
        / "static"
        / "console.css"
    ).read_text(encoding="utf-8")

    assert 'class="from-desk"' in html
    assert "idea-card.proposed" in css
    ground = css[css.index(".idea-card.proposed {") :]
    ground = ground[: ground.index("}")]
    assert "background-image" in ground or "border-left" in ground


@pytest.mark.unit
async def test_the_pool_can_be_sorted_by_where_an_idea_came_from(desk: Store) -> None:
    """ "По ним можно сортироваться." Finding all of one sort is the first thing anybody does."""
    mine = await inbox.capture(desk, "mine, written first", project_key=KEY)
    theirs = await inbox.capture(desk, "a proposal, written second", project_key=KEY, author="desk")

    await desk.set_setting(routes.IDEA_SORT_KEY, "proposed")
    html = await routes.render_ideas()
    assert html.index(theirs.id) < html.index(mine.id)

    await desk.set_setting(routes.IDEA_SORT_KEY, "mine")
    html = await routes.render_ideas()
    assert html.index(mine.id) < html.index(theirs.id)


@pytest.mark.unit
async def test_what_was_set_aside_can_be_found_again(desk: Store) -> None:
    """A list you can dismiss things from and never see again is a list nobody dismisses anything
    from."""
    from tests.unit.test_input import _post

    theirs = await inbox.capture(desk, "a proposal", project_key=KEY, author="desk")
    await desk.set_idea_state(theirs.id, "dropped")

    assert theirs.id not in await routes.render_ideas()

    await _post("/ideas/aside", {"aside": "yes"})
    shown = await routes.render_ideas()
    assert theirs.id in shown
    assert "back to the live ones" in shown

    await _post("/ideas/aside", {"aside": ""})
    assert theirs.id not in await routes.render_ideas()


@pytest.mark.unit
async def test_an_idea_made_from_a_conversation_belongs_to_the_person_who_had_it(
    desk: Store,
) -> None:
    """ "В финале… кнопка «добавить как идею» — собираем контекст из полученных карточек и
    формируем идею, помеченную как обычную, то есть мою."

    `human` is not a claim about who typed it. It means somebody now holds the context this idea
    grew out of — which, after a conversation they drove, they do.
    """
    from tests.unit.test_input import _post

    one = await desk.add_step_card("what it would take")
    await desk.set_card_role(one.name, "action")
    await desk.set_card_field(one.name, "do", "read the folder and name each file")
    await desk.card_made(one.name, "about a day, and it needs a model call per file")

    status, body, _ = await _post(
        "/ideas/from-bench",
        {"cards": one.name, "summary": "name the files in a folder card"},
    )
    assert status == 200

    made = next(idea for idea in await desk.ideas() if idea.summary.startswith("name the files"))
    assert made.author == "human", "an idea somebody talked their way to is still a proposal"
    assert "read the folder and name each file" in made.text
    assert "what came of it: about a day" in made.text


@pytest.mark.unit
async def test_making_an_idea_from_nothing_is_refused(desk: Store) -> None:
    from tests.unit.test_input import _post

    status, _, _ = await _post("/ideas/from-bench", {"cards": "", "summary": ""})

    assert status == 400
    assert await desk.ideas() == []
