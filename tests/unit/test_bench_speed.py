"""Reading the page's layout and writing to it, kept apart (01M1YQGZJZ…, a child of 01M1XC4Z0MA…).

"Двести карточек на верстаке не должны его убивать. Тридцать девять карточек уже сделали верстак
нечитаемым — это видели своими глазами."

Measured in a browser on 35 cards before this: one frame of a pan cost 20.6ms and `syncTargets`
36.8ms. The cause was not the number of cards but the order of the work — asking the browser how
big a card is, *after* having written to the document, forces it to lay the whole page out again to
answer, and both of the hot functions did that once per card. After: 3.8ms and 19.2ms, with the
same lines drawn, the same dots shown and the same counts beside the same cards.

A timing test would be the obvious thing here and it is the wrong one: it fails on a loaded machine
and passes on a fast one, and neither outcome says whether the mistake came back. The mistake has a
shape — a read after a write, in a loop — and that is what these assert.
"""

from __future__ import annotations

import pathlib
import re

import pytest

CONSOLE = (
    pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static" / "console.js"
)

# Asking any of these forces the browser to settle the layout before it can answer.
MEASURING = ("offsetWidth", "offsetHeight", "getBoundingClientRect", "clientWidth", "clientHeight")

# Any of these invalidates the layout the browser has just settled.
WRITING = ("appendChild(", "replaceChildren(", "textContent = ", "insertAdjacentHTML(")


def _body(name: str) -> str:
    """One function, from its signature to the closing brace in the first column."""
    source = "\n".join(
        line
        for line in CONSOLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    start = source.index(f"function {name}(")
    return source[start : source.index("\n}\n", start)]


def _reads_after_writing(body: str) -> list[str]:
    """Every measurement taken after the first write to the document.

    One read after one write is one forced layout. In a loop — which is what both of these are —
    it is one per card, which is the whole finding.
    """
    first_write = min(
        (body.index(one) for one in WRITING if one in body),
        default=len(body),
    )
    return [one for one in MEASURING if (found := body.find(one)) != -1 and found > first_write]


@pytest.mark.unit
def test_the_off_edge_dots_are_worked_out_rather_than_measured() -> None:
    """A card's place on the screen is arithmetic: the surface carries one transform, so screen-x
    is `view.x + at.x * scale`. Asking the browser instead cost 19ms of every frame of a pan."""
    body = _body("markOffEdge")

    assert body.count("getBoundingClientRect") == 1, (
        "the browser is asked where each card is again; it is asked once, for the frame, and the "
        "cards are worked out from the transform"
    )
    assert "view.x + at.x * view.scale" in body, (
        "the arithmetic that replaced the measuring is gone"
    )
    assert not _reads_after_writing(body), (
        f"a size is read after the document has been written to: {_reads_after_writing(body)}"
    )


@pytest.mark.unit
def test_the_lines_are_measured_before_any_of_them_is_drawn() -> None:
    body = _body("drawTies")

    assert not _reads_after_writing(body), (
        f"a card is measured after a line has been appended: {_reads_after_writing(body)}"
    )


@pytest.mark.unit
def test_a_line_does_not_search_the_whole_surface_for_its_own_ends() -> None:
    """`querySelector` per line, over a surface whose size grows with the number of cards, is the
    same curve as the forced layouts — it just does not show up in a profiler as one."""
    body = _body("drawTies")

    assert "querySelectorAll" in body and "querySelector(" not in body.replace(
        "querySelectorAll", ""
    ), "the ends of each line are still looked up one at a time"
    assert "pins.get(tie.from)" in body and "pins.get(tie.to)" in body


@pytest.mark.unit
def test_how_many_lines_reach_a_card_is_counted_once_for_all_of_them() -> None:
    """It was one walk over every line, for every card, on every redraw — the shape that turns a
    hundred cards into a surface that will not pan."""
    body = _body("markHintCounts")

    assert "everyTie()" not in body, "the count is still worked out per card"
    assert "function markHintCounts(holder, joined)" in body, (
        "the count is no longer handed in, so it has to be worked out somewhere"
    )


@pytest.mark.unit
def test_the_map_was_already_right_and_stays_that_way() -> None:
    """It reads every size first, builds the dots into a list, and puts them in once. Asserted
    because it is the pattern the other two now follow, and a regression here would be the same
    bug in the one place that never had it."""
    body = _body("drawMap")

    assert not _reads_after_writing(body)


@pytest.mark.unit
def test_nothing_else_on_the_hot_path_measures_after_writing() -> None:
    """The three functions a pan runs through. Named rather than swept for, so that adding a fourth
    is a decision instead of an omission."""
    for name in ("applyView", "settleOverlaps", "freeSpot"):
        assert not _reads_after_writing(_body(name)), f"{name} measures after writing"


@pytest.mark.unit
def test_the_reads_and_writes_this_looks_for_are_the_ones_that_matter() -> None:
    """The check above is a substring search, so it is worth proving it can actually fail."""
    bad = "function x() {\n  el.appendChild(y);\n  const w = el.offsetWidth;\n"
    good = "function x() {\n  const w = el.offsetWidth;\n  el.appendChild(y);\n"

    assert _reads_after_writing(bad) == ["offsetWidth"]
    assert _reads_after_writing(good) == []


@pytest.mark.unit
def test_every_hot_function_is_still_there_under_the_name_the_page_calls_it_by() -> None:
    """These are asserted by name above, so a rename would quietly stop checking them."""
    console = CONSOLE.read_text(encoding="utf-8")
    for name in ("markOffEdge", "drawTies", "drawMap", "markHintCounts"):
        assert len(re.findall(rf"\b{name}\(", console)) > 1, f"{name} is defined and never called"
