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


@pytest.mark.unit
def test_a_drag_ends_even_when_the_card_does_not() -> None:
    """ "При передвижении с помощью ЛКМ на верстаке некорректное поведение."

    The pointer was captured on the card and the release was listened for on the canvas. Cards are
    removed and rebuilt while an answer streams in, so a card that went away mid-drag took the
    capture with it, `pointerup` fired on nothing, and `moving` stayed set — the card then followed
    the cursor with no button held.

    Two halves to the fix, and both are asserted: the capture goes on the canvas, which does not
    come and go, and the release is heard on the window, which catches a mouse let go anywhere.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "canvas.setPointerCapture" in console, "the gesture is captured on the card again"
    assert "pin.setPointerCapture" not in console, (
        "the card still captures the pointer, so removing it mid-drag strands the gesture"
    )
    for event in ("pointerup", "pointercancel", "lostpointercapture", "blur"):
        assert f"window.addEventListener('{event}', endMove)" in console, (
            f"a drag is not ended on {event}, so it can outlive the button being let go"
        )


@pytest.mark.unit
def test_a_drag_does_not_write_to_disk_on_every_pointer_event() -> None:
    """The other half of "не всегда получается адекватно перемещаться": it stuttered.

    `place` serialises the position of every card on the bench into localStorage. A pointer
    reports faster than the screen refreshes, so a drag was doing a synchronous disk write and a
    full rebuild of the tie layer per event, most of it thrown away before it was ever painted.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "remember = true" in console, "place has no way to defer the write"
    assert console.count("{ avoid: false, remember: false }") >= 2, (
        "the drag still writes the whole layout to localStorage on every pointer event"
    )
    assert "requestAnimationFrame" in console and "function redrawSoon(" in console, (
        "the ties and rings are still redrawn per pointer event rather than per frame"
    )

    move = console[console.index("canvas?.addEventListener('pointermove'") :]
    move = move[: move.index("\n});")]
    assert "drawTies()" not in move, "drawTies is still called straight from the move handler"


@pytest.mark.unit
def test_a_card_is_a_handle_and_not_only_its_title_bar() -> None:
    """Only `.pin-head` could move a card — a strip a few pixels tall on a card of 260 by 200.

    A press anywhere else did nothing at all: not a move, because it was not on the head, and not
    a pan, because it was inside a card. Most of what somebody aims at is the card.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "function gripOf(" in console, "there is no rule for what may be grabbed"
    grip = console[console.index("function gripOf(") :]
    grip = grip[: grip.index("\n}\n")]
    assert "NOT_A_GRIP" in grip, "buttons and links are grabbable, so pressing one drags the card"
    assert "'hint'" in grip, (
        "a folded card is not a handle all over; only its head moves it, which is the dead zone "
        "this was reported as"
    )


@pytest.mark.unit
def test_a_settling_pass_does_not_take_a_card_out_of_somebody_s_hand() -> None:
    """A press that has not travelled four pixels is not yet a drag and has not set `data-moved`.

    `settleOverlaps` moves every card without that mark, and it fires 60ms after any card's body
    updates — which, while an answer streams, is constantly. Landing in that window teleported the
    card the mouse was holding.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    settle = console[console.index("function settleOverlaps(") :]
    settle = settle[: settle.index("\n}\n")]
    assert "moving" in settle, "a settling pass will still move the card being dragged"


@pytest.mark.unit
def test_the_arrow_keys_move_a_card_and_pan_when_none_is_chosen() -> None:
    """ "На стрелочки тоже добавь перемещение."

    And the two things that make it usable rather than nominal: a card has to be able to take
    focus, or there is nothing for a key to move; and typing in the message field has to keep
    moving the caret, or the page steals the arrow keys from the thing it is mostly used for.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "const ARROWS" in console and "function nudge(" in console
    assert console.count("tabIndex = 0") >= 3, (
        "not every kind of card can take focus, so the arrow keys reach only some of them"
    )

    handler = console[
        console.index("document.addEventListener('keydown', (event) => {\n  const step = ARROWS") :
    ]
    handler = handler[: handler.index("\n});")]
    assert "input, textarea, select" in handler, (
        "the arrow keys are taken from the message field, where they move the caret"
    )
    assert "alsoMoving" in console[console.index("function nudge(") :][:400], (
        "a keyboard move breaks up a group that a pointer move keeps together"
    )


@pytest.mark.unit
def test_the_column_handles_have_a_width_to_grab() -> None:
    """ "Куда-то пропала возможность менять ширину столбцов."

    Here is where it went: two empty divs in a flex row with no size on them anywhere in the
    stylesheet laid out at zero pixels wide. Present in the markup, keyboard-reachable, and
    impossible to hit with a mouse — while `.gutter.across`, which sets its own flex, kept
    working. That asymmetry is why it read as something that had disappeared.
    """
    css = (STATIC / "console.css").read_text(encoding="utf-8")
    board = (TEMPLATES / "board.html").read_text(encoding="utf-8")

    assert board.count('class="gutter"') == 2, "the two vertical handles are not on the page"

    rule = css[css.index("\n.gutter {") :]
    rule = rule[: rule.index("}")]
    assert "width:" in rule and "flex:" in rule, (
        "the vertical gutters have no size, so they lay out at zero pixels and cannot be grabbed"
    )


@pytest.mark.unit
def test_nothing_sits_between_the_bench_and_the_columns_but_the_handle() -> None:
    """ "Давай сделаем промежуток между верстаком и столбцами меньше, либо вообще уберём."

    The gap was six pixels of nothing on each side, on top of a handle that was zero wide. Now the
    handle is the space: seven pixels that can be grabbed, and no dead gap beside it.
    """
    css = (STATIC / "console.css").read_text(encoding="utf-8")

    grid = css[css.index(".desk-grid {") :]
    grid = grid[: grid.index("}")]
    assert "gap: 0" in grid, "there is dead space between the columns again"
