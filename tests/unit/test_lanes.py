"""A lane beside the sessions is added in web/lanes.py, and routes.py does not change (task 22)."""

from __future__ import annotations

import pathlib

import pytest
from agent_desk.web import lanes, routes

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_a_new_lane_reaches_both_renderings_of_the_board(monkeypatch: pytest.MonkeyPatch) -> None:
    def a_new_one() -> lanes.Lane:
        return lanes.Lane({"pull_lines": ["PR · somebody/else: 2 open"]}, ["a lane had a notice"])

    monkeypatch.setattr(lanes, "LANES", [*lanes.LANES, a_new_one])

    page = routes.render_board()

    assert "PR · somebody/else: 2 open" in page
    assert "a lane had a notice" in page


async def test_the_whole_page_renders_the_lanes_too(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_desk.store.repo import Store

    monkeypatch.setattr(lanes, "LANES", [*lanes.LANES, lambda: lanes.Lane(notices=["from a lane"])])
    store = Store(tmp_path / "agent-desk.db")
    monkeypatch.setattr(routes, "store", store)
    await store.open()
    try:
        page = await routes.render_page()
    finally:
        await store.close()

    assert "from a lane" in page


def test_routes_names_no_lane_by_what_it_reads() -> None:
    """The point of the module: routes.py renders `**beside.fields` and knows no lane's source."""
    source = (ROOT / "agent_desk" / "web" / "routes.py").read_text(encoding="utf-8")

    for name in ("read_jobs", "pulls.lines", "waiting_jobs=", "pull_lines="):
        assert name not in source
