"""What is served out of `static/`, including the one file this project did not write.

A vendored dependency that can be replaced without anybody noticing is not vendored, it is just
old. So the hash is asserted here, and changing the file without changing this test is a failing
gate rather than a surprise in somebody's browser.
"""

from __future__ import annotations

import hashlib
import pathlib
import re

import pytest

STATIC = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "static"
TEMPLATES = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "templates"

# htmx 2.0.4, fetched from unpkg and jsdelivr and kept only because their bytes matched.
# See agent_desk/web/static/VENDORED.md.
HTMX = "e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447"


@pytest.mark.unit
def test_htmx_is_vendored_and_is_the_file_it_says_it_is() -> None:
    """docs/adr/0003: a local tool that needs the network to render a list of five sessions has
    lost the argument. A console you open when something has gone wrong has to work when the
    something is your connection."""
    where = STATIC / "htmx.min.js"

    assert where.exists(), "htmx is not vendored; the console degrades and says so in a banner"
    assert hashlib.sha256(where.read_bytes()).hexdigest() == HTMX, (
        "the vendored htmx is not the file VENDORED.md records. Either it was replaced without "
        "updating this test, or the checkout is damaged."
    )


@pytest.mark.unit
def test_what_it_is_and_where_it_came_from_is_written_down() -> None:
    """A blob in a repository with no provenance is a blob nobody can ever safely update."""
    said = (STATIC / "VENDORED.md").read_text()

    assert HTMX in said
    assert "2.0.4" in said
    assert "unpkg" in said and "jsdelivr" in said


@pytest.mark.unit
def test_nothing_on_a_page_is_fetched_from_somebody_else_s_server() -> None:
    """The whole argument for vendoring, asserted against every template rather than remembered.

    A `src` or an `href` pointing at a CDN is a page that goes blank on a train, and — for a
    console that renders transcript text — a third party who gets told every time it is opened.
    """
    offenders: list[str] = []
    for page in [*TEMPLATES.glob("*.html"), *TEMPLATES.glob("shared/*.html")]:
        for match in re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', page.read_text()):
            if match.startswith(("http://", "https://", "//")):
                # A link somebody clicks is fine; a resource the page loads is not.
                offenders.append(f"{page.name}: {match}")

    # Links out (a repository page, a tracker) are `href`s on anchors and are expected. What must
    # not appear is a stylesheet, a script or a font from anywhere but this machine.
    loaded = [one for one in offenders if "/static/" in one or one.endswith((".js", ".css"))]
    assert loaded == [], f"a page loads something from the network: {loaded}"


@pytest.mark.unit
def test_the_console_still_works_with_the_library_missing() -> None:
    """The banner is the promise: the common half is implemented here, so a checkout without the
    vendored file degrades to whole-page navigation rather than to a dead page."""
    script = (STATIC / "console.js").read_text()

    assert "if (!window.htmx)" in script
    assert "hx-post" in script and "hx-target" in script


@pytest.mark.unit
def test_a_browser_that_has_never_chosen_a_size_gets_the_full_one() -> None:
    """`localStorage.getItem` returns null when nothing is stored, and `Number(null)` is 0 — a
    perfectly valid index into the zoom scale. The first version of this therefore handed every
    browser that had never chosen a size the *smallest* one, which under the scale it shipped with
    was 50%: the console arrived at half size for everybody, with nothing on screen saying why.

    Asserted against the source because there is no JavaScript runtime in this gate. The shape
    that was wrong is `Number(getItem(...))` used directly as an index, and the shape that is
    right checks for the absent case before converting."""
    script = (STATIC / "console.js").read_text()

    assert "stored === null ? 1" in script, (
        "the absent case must be handled before the string becomes a number"
    )
    assert "Number(localStorage.getItem" not in script, (
        "Number(null) is 0, which was a valid index and therefore a silent wrong default"
    )
    # And what is stored is the *size*, not a position in a list that is allowed to change.
    # When that list gained two entries, every browser holding a "2" silently started meaning
    # 80% where it had meant 100% — the same class of bug twice in one control.
    assert "String(next)" in script
    assert "ZOOMS.indexOf(next)" not in script
    assert "ZOOMS.includes(remembered)" in script


@pytest.mark.unit
def test_full_size_is_the_default_and_the_way_back_to_it_is_one_press() -> None:
    """The bench is a diagram surface, so half size is a perfectly good *choice* — seeing the whole
    layout at once is what a zoom is for. What was wrong was never the range: it was that the
    smallest was what you got without choosing, and that there was nothing obvious to press to
    undo it. So the invariant is the default and the escape hatch, not a floor."""
    script = (STATIC / "console.js").read_text()
    scale = re.search(r"const ZOOMS = \[([0-9., ]+)\]", script)
    assert scale is not None

    sizes = [float(one) for one in scale.group(1).split(",")]
    assert 1 in sizes, "there has to be a full size to go back to"
    assert "const FULL_SIZE = ZOOMS.indexOf(1)" in script, "the default is full size, by name"
    # And pressing the middle control puts the whole view back, not just the scale.
    assert "view = { x: 0, y: 0, scale: 1 }" in script


@pytest.mark.unit
def test_nothing_on_the_page_is_smaller_than_twelve_pixels() -> None:
    """A console is read at a glance, across a desk, at the end of a long day. This page had 9px
    and 10px text on it, which is legible on the machine it was written on and nowhere else."""
    css = (STATIC / "console.css").read_text()

    raw = re.findall(r"font-size:\s*([0-9.]+)(px|rem)", css)
    assert raw == [], f"a size that is not on the scale: {raw}"

    scale = dict(re.findall(r"--t-(x?s|m?d|lg|xl):\s*([0-9]+)px", css))
    for name, size in scale.items():
        assert int(size) >= 12, f"--t-{name} is {size}px"


@pytest.mark.unit
def test_a_folded_card_says_what_it_is_and_not_only_which_one_it_is() -> None:
    """ "Сейчас плохо отображаются хинты, практически не видно что из себя представляют."

    A folded card used to show its title clamped to two lines, and a title is a name — it says
    *which* card this is, never what it holds. The sentence written about the card is the thing
    that answers that, and it lives in the body, which is exactly what folding hides.

    So it is lifted into the head as `.pin-hint`, and this asserts the two halves that make that
    true: the console writes one, and the stylesheet shows it only while the card is folded.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    css = (STATIC / "console.css").read_text(encoding="utf-8")

    assert "function writeHint(" in console, "nothing lifts a description out of a folded body"
    assert "'.card-said'" in console, (
        "the hint does not prefer the sentence a model wrote about the card, which is the one "
        "line on it written to answer 'what is this'"
    )
    assert ".pin-hint" in css, "the lifted hint has no style, so it renders as unclassed text"
    assert '.pin[data-view="hint"] .pin-hint' in css, (
        "the hint is not scoped to the folded view; an open card would then say the same sentence "
        "twice, once in the hint and once in the body it came from"
    )


@pytest.mark.unit
def test_a_hint_is_two_lines_and_the_title_above_it_is_one() -> None:
    """ "Делаем так — хинт 2 строки максимум." Two lines of meaning, over one line of name.

    The clamp used to be on `.pin-label`, which spent both lines repeating the title. Asserting
    where the clamp *is* is the only way that mistake stays fixed, because both versions look
    tidy in a screenshot.
    """
    css = (STATIC / "console.css").read_text(encoding="utf-8")

    hint = css[css.index('.pin[data-view="hint"] .pin-hint') :]
    hint = hint[: hint.index("}")]
    assert "line-clamp: 2" in hint, "the hint is not held to two lines"

    label = css[css.index(".pin-label {") :]
    label = label[: label.index("}")]
    assert "line-clamp" not in label, (
        "the title is clamped to several lines again, which is what left a folded card with no "
        "room for anything but its own name"
    )
    assert "text-overflow: ellipsis" in label, "the one-line title has no ellipsis to cut it"


@pytest.mark.unit
def test_what_went_out_as_one_question_moves_as_one_group() -> None:
    """ "При запуске в обработку несколько выделенных карточек как контекст — они перемещаются
    вместе, рамка работы образуется только вокруг этой группы."

    The frame was already drawn around that set and nothing else. The half that was missing is
    that the set behaved like one: dragging any card out of a ring left the frame stretching to
    follow it, which is a frame around a shape nobody arranged.

    Being joined by a line is deliberately *not* enough — see `alsoMoving`. A line is a relation,
    and pulling the two ends of a relation apart is a thing somebody does on purpose.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "function alsoMoving(" in console, "a card has no notion of what moves with it"
    assert "with: alsoMoving(pin)" in console, (
        "the group is never gathered when the drag starts, so there is nothing to move with it"
    )
    together = console[console.index("function alsoMoving(") :]
    together = together[: together.index("\n}\n")]
    assert "'.ring'" in together, "the group is not read from the rings"
    assert "ownTies" not in together and "everyTie" not in together, (
        "a line is being treated as a group; dragging one end of a relation away from the other "
        "is a thing somebody does on purpose"
    )
