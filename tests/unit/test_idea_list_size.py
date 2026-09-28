"""The ideas column grows with the pool, not with its square (B6, _research/04_dogfooding_gaps.md).

Every card carried a <select> of every other idea, so two hundred open ideas rendered 3.7 MB. One
shared <datalist> is the same choices, once.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


async def _rendered_with(desk: Store, count: int) -> int:
    for number in range(len(await desk.ideas()), count):
        text_ = f"idea number {number}, long enough to be a real sentence about some real work"
        await desk.create_idea(text_=text_, summary=text_, source_kind="typed")
    html = await routes.render_ideas()
    assert html.count('<datalist id="idea-choices">') == 1
    return len(html.encode())


async def test_twice_the_ideas_is_about_twice_the_page_not_four_times(desk: Store) -> None:
    """Measured 2026-09-27: ~3.5 KB an idea, 0.71 MB at two hundred (it was 3.7 MB)."""
    hundred = await _rendered_with(desk, 100)
    two_hundred = await _rendered_with(desk, 200)

    assert two_hundred / hundred < 2.2
    assert two_hundred < 800_000


async def test_a_link_to_an_idea_that_is_not_there_is_not_stored(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other idea is typed now, not picked, so it can name nothing — and must not 500."""
    one = await desk.create_idea(text_="a", summary="a", source_kind="typed")
    other = await desk.create_idea(text_="b", summary="b", source_kind="typed")

    said: dict[str, str] = {}

    async def form(request: object) -> dict[str, str]:
        return said

    monkeypatch.setattr(routes, "_form", form)
    for to_id in ("no-such-idea", other.id):
        said.update(from_id=one.id, to_id=to_id, kind="needs")
        await routes.link_ideas(type("R", (), {"headers": {"hx-request": "true"}})())  # type: ignore[arg-type]

    assert [(link.from_id, link.to_id) for link in await desk.idea_links()] == [(one.id, other.id)]
