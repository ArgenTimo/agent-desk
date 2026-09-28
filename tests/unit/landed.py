"""A task as a console that still landed branches left it (032-task-landed.sql).

Nothing in this program writes `task.landed` any more (docs/adr/0013), but the column stays and the
code that reads it — the blockers column, `later.gate_is_green` — has to keep reading rows written
before then. The store has no writer for it, so the tests write the row the way that console did.
"""

from __future__ import annotations

from agent_desk.store.repo import Store
from sqlalchemy import text


async def as_landed(store: Store, task_id: str, detail: str, *, landed: bool) -> None:
    async with store.engine.begin() as conn:
        await conn.execute(
            text("UPDATE task SET detail = :detail, landed = :landed WHERE id = :id"),
            {"detail": detail, "landed": int(landed), "id": task_id},
        )
