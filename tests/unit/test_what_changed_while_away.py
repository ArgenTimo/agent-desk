"""A card could say when it last changed, not only when it arrived (01M25VH7AXXJ1AT09AHE77J2W4).

docs/stories/01, story 5: "coming back to a bench that changed shows what changed". What shipped
first could only honestly say *arrived*, because `cameAt` never moves. A run moving a step on is
the writer that works while nobody is looking, and it now leaves a time behind.

The helpers are run in node rather than matched as text: a comparison that reads right and answers
wrong is exactly what a string assertion cannot see.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.unit

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)


def _function(code: str, name: str) -> str:
    body = code[code.index(f"function {name}(") :]
    return body[: body.index("\n}\n") + 2]


def _run(expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on this machine")
    code = CONSOLE.read_text(encoding="utf-8")
    helpers = "\n".join(
        _function(code, name) for name in ("stepSays", "changedBetween", "whatHappenedSince")
    )
    done = subprocess.run(  # noqa: S603 — a fixed argv; the script is this repository's own code
        [node, "-e", f"{helpers}\nprocess.stdout.write(JSON.stringify({expression}));"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_step_that_moved_on_is_a_change() -> None:
    before = {"state": "going", "made": ""}
    after = {"state": "done", "made": "## the answer"}

    assert _run(f"changedBetween(stepSays({json.dumps(before)}), stepSays({json.dumps(after)}))")


def test_the_same_answer_read_again_is_not_a_change() -> None:
    """The runs are read every twenty seconds. A card stamped on every read would be marked
    "changed" whenever a run exists at all, which is a mark that says nothing."""
    step = json.dumps({"state": "done", "made": "## the answer"})

    assert _run(f"changedBetween(stepSays({step}), stepSays({step}))") is False


def test_the_first_reading_is_not_a_change() -> None:
    """How the card was when the page met it. Nobody saw an earlier state for it to differ from."""
    step = json.dumps({"state": "done", "made": ""})

    assert _run(f"changedBetween(undefined, stepSays({step}))") is False


def test_a_card_a_run_reached_while_away_is_a_change() -> None:
    """A run has no row for a step until the engine gets to it (`set_run_step`), so every card
    after the first one goes from not being a step to being one. Read as "the first reading", that
    was most of a run left going — the exact thing the mark exists for."""
    step = json.dumps({"state": "done", "made": "## the answer"})

    assert _run(f"changedBetween(stepSays(undefined), stepSays({step}))") is True


def test_a_card_that_stopped_being_a_step_is_not_marked() -> None:
    """Switching benches empties the run list for it; that is not something that happened to it."""
    step = json.dumps({"state": "done", "made": ""})

    assert _run(f"changedBetween(stepSays({step}), stepSays(undefined))") is False


@pytest.mark.parametrize(
    ("came_at", "changed_at", "want"),
    [
        (200, 0, "arrived"),
        (50, 200, "changed"),
        # Came and then ran while away: its first state was never seen, so it arrived.
        (150, 200, "arrived"),
        (50, 80, ""),
        (50, 0, ""),
    ],
)
def test_what_happened_since_the_window_went_away(came_at: int, changed_at: int, want: str) -> None:
    assert _run(f"whatHappenedSince({came_at}, {changed_at}, 100)") == want


def test_the_run_is_what_stamps_it() -> None:
    """The one writer that works while the window is in the background. Nowhere else stamps it —
    a press somebody made while looking cannot be something that happened while they were away."""
    code = CONSOLE.read_text(encoding="utf-8")

    assert "pin.dataset.changedAt = " in _function(code, "showRuns")
    assert code.count("dataset.changedAt = ") == 1


def test_coming_back_reads_the_runs_before_marking() -> None:
    """A background tab polls a minute apart at best; a run that finished in that minute would
    otherwise be missing from the one mark that is about it."""
    code = CONSOLE.read_text(encoding="utf-8")
    handler = code[code.index("document.addEventListener('visibilitychange'") :]
    handler = handler[: handler.index("\n});\n")]

    assert handler.index("await readRuns()") < handler.index("markWhatArrivedSince(since)")


def test_going_away_again_during_the_read_keeps_the_earlier_absence() -> None:
    """The read is a round trip. A window hidden again before it answers is still the same absence,
    and marking against the later moment would drop what changed in between."""
    code = CONSOLE.read_text(encoding="utf-8")
    handler = code[code.index("document.addEventListener('visibilitychange'") :]
    handler = handler[: handler.index("\n});\n")]
    after_read = handler[handler.index("await readRuns()") :]

    assert "lookedAwayAt = since" in after_read[: after_read.index("markWhatArrivedSince(since)")]


def test_the_mark_says_which_of_the_two_it_is() -> None:
    code = CONSOLE.read_text(encoding="utf-8")
    marking = _function(code, "markWhatArrivedSince")
    forgetting = _function(code, "forgetWhatArrived")

    assert "changed-since" in marking and "arrived-since" in marking
    assert "changed-since" in forgetting
    css = CONSOLE.with_name("console.css").read_text(encoding="utf-8")
    assert ".pin.changed-since" in css
