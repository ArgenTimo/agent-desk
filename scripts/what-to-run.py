"""Which test files could be about the change in the working tree.

«За смену я прогнал `make verify` больше тридцати раз, по четыре с лишним минуты.» This says which
of them could possibly be about the two or three files that changed — and says, every time, that it
is not the gate.

    make what-to-run          # against origin/main
    make what-to-run AT=HEAD  # against the last commit
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_desk import narrowing


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    against = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    diff = subprocess.run(  # noqa: S603 — a fixed argv in this repository
        ["git", "diff", "--unified=0", against],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    if diff.returncode:
        print(f"could not read the diff against {against}: {diff.stderr.strip()}")
        return 1
    changed = narrowing.read_the_diff(diff.stdout, root=root)
    if not changed.files:
        print(f"Nothing has changed against {against}.")
        return 0
    tests = {
        str(one.relative_to(root)): one.read_text(encoding="utf-8")
        for one in sorted((root / "tests").rglob("test_*.py"))
    }
    wanted, always = narrowing.what_to_run(changed, tests)
    if changed.opaque:
        print(
            "Something changed that this cannot read as Python — "
            + ", ".join(sorted(changed.opaque))
            + " — so every test file is in."
        )
    print(narrowing.as_text(wanted, always, len(tests)))
    print()
    print("poetry run pytest -m unit " + " ".join(wanted))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
