"""A row with tracker 'git' is kept and is not a filing (task 19, _work/DECISIONS.md D13).

259 such rows sit in the live database — commit URLs recorded against ideas by something outside
this code. They are not deleted; nothing reads them as "filed in a tracker".
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk.store.repo import Store

pytestmark = pytest.mark.unit


async def test_only_a_tracker_filing_is_a_filing_and_the_other_row_stays(
    tmp_path: pathlib.Path,
) -> None:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    try:
        built = await store.create_idea(text_="built", summary="built", source_kind="typed")
        filed = await store.create_idea(text_="filed", summary="filed", source_kind="typed")
        await store.record_filing(
            idea_id=built.id, tracker="git", issue_key="4f2a1c", url="https://x/commit/4f2a1c"
        )
        await store.record_filing(
            idea_id=filed.id, tracker="jira", issue_key="ADSK-1", url="https://x/ADSK-1"
        )

        assert [one.issue_key for one in await store.filings()] == ["ADSK-1"]
        assert await store.filing_of(built.id) is None
        assert (await store.filing_of(filed.id)).issue_key == "ADSK-1"  # type: ignore[union-attr]
        async with store.engine.connect() as conn:
            from sqlalchemy import text

            kept = (await conn.execute(text("SELECT COUNT(*) FROM filing"))).scalar_one()
        assert kept == 2
    finally:
        await store.close()
