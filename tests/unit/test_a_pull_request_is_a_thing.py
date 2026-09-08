"""A pull request as a thing, not only as a reason something stopped
(01M1ZQ3JQ1Q209KZ3337TGW611).

"PR-ы читаются и складываются в блокеры… Это правда про PR, который ждёт ревью, и неправда про PR
вообще — на верстаке он нужен как вещь, про которую спрашивают, рядом с сессией, которая его
написала."

Both readings are true at once and they are different cards. The blockers column keeps saying "this
has stopped on a person"; this says what it is.

Part of "Вынести на верстак то, к чему есть доступ" (01M1X8DA5KM5K6VZDKWKM664Y0).
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import roles
from agent_desk.store.repo import Pull, Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
BLOCKER_CARD = HERE / "agent_desk" / "web" / "templates" / "_card_blocker.html"
AUTOSTART = HERE / "agent_desk" / "web" / "autostart.py"

KEY = "origin:acme/api"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _pull(number: int = 12, **over: object) -> Pull:
    said: dict[str, object] = {
        "repo_key": KEY,
        "number": number,
        "title": "drop the trailing slash",
        "url": "https://github.com/acme/api/pull/12",
        "waiting_for": "a review",
        "seen_at": 0,
    }
    return Pull(**{**said, **over})  # type: ignore[arg-type]


# --- the store ------------------------------------------------------------------------------------
async def test_what_was_read_comes_back(desk: Store) -> None:
    await desk.replace_pulls(KEY, [_pull()])

    (back,) = await desk.pulls(KEY)
    assert (back.number, back.title, back.waiting_for) == (
        12,
        "drop the trailing slash",
        "a review",
    )
    assert back.url.endswith("/pull/12")


async def test_a_draft_survives_the_write(desk: Store) -> None:
    """`github.Pull` has read it all along and `replace_pull_blockers` dropped it, because a
    blocker does not need it and a card does."""
    await desk.replace_pulls(KEY, [_pull(draft=True)])

    (back,) = await desk.pulls(KEY)
    assert back.draft is True


async def test_a_merged_one_is_gone_on_the_next_read(desk: Store) -> None:
    """Written whole rather than as a diff: this is a copy of somebody else's list, and the
    smallest message that can say "that one was merged" is the list without it."""
    await desk.replace_pulls(KEY, [_pull(12), _pull(13)])
    await desk.replace_pulls(KEY, [_pull(13)])

    assert [one.number for one in await desk.pulls(KEY)] == [13]


async def test_another_project_keeps_its_own(desk: Store) -> None:
    """A pull request number means nothing outside the repository it belongs to, which is why
    neither half of the key is a key on its own."""
    await desk.replace_pulls(KEY, [_pull(12)])
    await desk.replace_pulls("origin:acme/web", [_pull(12, repo_key="origin:acme/web")])

    assert len(await desk.pulls(KEY)) == 1
    assert len(await desk.pulls()) == 2


async def test_a_number_that_is_not_there_is_none(desk: Store) -> None:
    await desk.replace_pulls(KEY, [_pull(12)])

    assert await desk.pull(KEY, 99) is None


# --- the card -------------------------------------------------------------------------------------
async def test_it_is_a_thing_rather_than_a_step() -> None:
    """It appears in the blockers as an Event — "this stopped on a person" — and that is a
    different card saying a different thing about the same pull request."""
    assert roles.role_of("pull").name == "object"
    assert roles.role_of("blocker").name == "event"


async def test_the_card_says_what_it_is_and_what_it_waits_for(desk: Store) -> None:
    await desk.replace_pulls(KEY, [_pull()])

    answer = await routes.card("pull", f"{KEY}::#12")
    body = bytes(answer.body).decode()

    assert answer.status_code == 200
    assert "drop the trailing slash" in body
    assert "a review" in body


async def test_an_open_one_with_nobody_named_says_that_rather_than_nobody(desk: Store) -> None:
    """An empty answer is a real one, and "nobody" would be a claim."""
    await desk.replace_pulls(KEY, [_pull(waiting_for="")])

    body = bytes((await routes.card("pull", f"{KEY}::#12")).body).decode()

    assert "nothing about it says who is next" in body


async def test_a_draft_says_it_is_not_asking_for_a_review(desk: Store) -> None:
    await desk.replace_pulls(KEY, [_pull(draft=True)])

    body = bytes((await routes.card("pull", f"{KEY}::#12")).body).decode()

    assert "not asking for a review yet" in body


async def test_the_card_offers_the_link_and_claims_nothing_else(desk: Store) -> None:
    """docs/adr/0010: this console reads. The place where a pull request is reviewed is GitHub, and
    the card sends you there rather than growing a button."""
    await desk.replace_pulls(KEY, [_pull()])

    body = bytes((await routes.card("pull", f"{KEY}::#12")).body).decode()

    assert "https://github.com/acme/api/pull/12" in body
    assert "reads pull requests and does nothing else with them" in body
    assert "approve" not in body.lower()
    assert "merge" not in body.lower()


async def test_one_that_has_been_merged_says_so_rather_than_erroring(desk: Store) -> None:
    answer = await routes.card("pull", f"{KEY}::#404")

    assert answer.status_code == 404
    assert "not open any more" in bytes(answer.body).decode()


async def test_a_name_that_is_not_a_pull_request_is_not_read_as_one(desk: Store) -> None:
    """The id is split on the separator rather than trusted: a project key contains colons, and a
    reader that took the last one would have asked for pull request number `api`."""
    assert (await routes.card("pull", "nonsense")).status_code == 404
    assert (await routes.card("pull", f"{KEY}::#not-a-number")).status_code == 404


# --- and how one reaches the bench ------------------------------------------------------------------
def test_a_stopped_pull_request_offers_itself_as_a_card() -> None:
    """Otherwise the kind is unreachable: nothing else on the page names one yet."""
    markup = BLOCKER_CARD.read_text(encoding="utf-8")

    assert 'data-kind="pull"' in markup
    assert 'data-id="{{ one.repo_key }}::{{ one.ref }}"' in markup
    assert 'draggable="true"' in markup


def test_both_readings_are_written_on_every_read() -> None:
    """The blockers were right and stay exactly as they were; the pull rows are the other reading
    of the same fact."""
    source = AUTOSTART.read_text(encoding="utf-8")

    assert "store.replace_pull_blockers(" in source
    assert "store.replace_pulls(" in source
