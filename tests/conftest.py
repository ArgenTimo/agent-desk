"""The machine this suite runs on is not an input to it.

`Settings` resolves `claude_home` and `data_dir` from the environment (config.py), and half the
package binds `settings` at module import. So the redirect has to happen here, at the top of the
one file pytest loads before any test module — an empty `~/.claude` and an empty `data_dir` for
every test, whether or not it remembered to ask for them.

It is a guard against one defect, and the defect has now happened twice. A test that renders the
board without redirecting reads the real registry and then the tail of every live session on this
machine, so its assertions are about whatever an agent working beside the suite happened to be
saying: `test_a_board_rendered_without_the_number_shows_no_number` asserted the word "today" was
absent and failed the moment a live session wrote that word in a sentence, having passed in the
same `make verify` ten minutes earlier (01M1ZEN85PA2NYSV70H59ZZFWN). The store half is the same
shape with worse consequences — `web/routes.py` opens `settings.db_path` at import, which without
this is the console's own database, live, while its owner is using it.

The third path out is not a read at all, and it is the one worth being explicit about. Every
surface that spawns something resolves `settings.claude_bin`: `answer/session.py` execs it to ask
a question, `dispatch.py` execs it to *start an agent* in a working directory, `opening.py` hands
it to a terminal emulator. Its default is `claude`, which on the machine this suite runs on is on
PATH and works. Every test today overrides it — but that is a convention, and the two paragraphs
above are what a convention is worth here. So it is pointed at a name inside the empty tree that
nothing will ever create: a test that forgets now reaches `needs_toolchain` from the answer
engine and "is not installed here" from `dispatch`, instead of spending somebody's money or
leaving a headless agent running in a repository nobody pointed it at.

Set rather than defaulted: an `AGENT_DESK_CLAUDE_HOME` already in somebody's environment is
exactly the value this must not use.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_ELSEWHERE = Path(tempfile.mkdtemp(prefix="agent-desk-suite-"))
(_ELSEWHERE / "claude" / "sessions").mkdir(parents=True)
(_ELSEWHERE / "claude" / "projects").mkdir(parents=True)
os.environ["AGENT_DESK_CLAUDE_HOME"] = str(_ELSEWHERE / "claude")
os.environ["AGENT_DESK_DATA_DIR"] = str(_ELSEWHERE / "data")
os.environ["AGENT_DESK_CLAUDE_BIN"] = str(_ELSEWHERE / "no-answer-engine-here")


def pytest_sessionfinish() -> None:
    """Take the empty tree away again, so a hundred runs are not a hundred directories."""
    shutil.rmtree(_ELSEWHERE, ignore_errors=True)
