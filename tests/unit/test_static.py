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
def test_what_went_out_ends_up_in_front_of_you() -> None:
    """ "Тот набор карточек, что взят сейчас в работу при отправке последнего запроса, должен
    перемещаться в центр экрана."

    The snapshot is placed clear of everything already on the bench, which means below it — and on
    a bench of forty cards that is off the bottom of the window. Somebody pressed send and the
    record of what they sent appeared where they could not see it, which is the same as it not
    appearing."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    start = console.index("document.getElementById('ask').addEventListener('submit'")
    body = console[start : console.index("\n});", start)]

    assert "bringTheseIntoView(" in body
    assert body.index("ringWhatWentWithIt();") < body.index("bringTheseIntoView("), (
        "it looks for the ring before the ring exists"
    )


@pytest.mark.unit
def test_bringing_a_group_into_view_moves_the_view_and_not_the_cards() -> None:
    """A layout somebody arranged by hand is not the console's to rearrange because a question was
    asked (042) — and moving the cards would take them out from under the lines drawn to them."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    start = console.index("function bringTheseIntoView(")
    body = console[start : console.index("\n}\n", start)]

    assert "place(" not in body and "dataset.moved" not in body
    assert "view.x =" in body and "view.y =" in body


@pytest.mark.unit
def test_it_zooms_out_to_fit_and_never_in() -> None:
    """Sending a question is not a reason to magnify a bench, and a zoom that moved in both
    directions on every send would be a surface nobody could hold still."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    start = console.index("function bringTheseIntoView(")
    body = console[start : console.index("\n}\n", start)]

    assert "if (fits < view.scale) {" in body


@pytest.mark.unit
def test_the_wheel_zooms_the_bench_without_a_modifier() -> None:
    """ "Без нажатия ctrl колёсико мыши не задействовано — давай скейлинг на него повесим." It was
    doing nothing else: the canvas is `overflow: hidden`, so a plain wheel over the bench scrolled
    nothing and zoomed nothing."""
    script = (STATIC / "console.js").read_text()
    start = script.index("canvas?.addEventListener(\n  'wheel',")
    body = script[start : script.index("{ passive: false }", start)]

    assert "if (!event.ctrlKey) return;" not in body, "it still asks for a modifier"
    assert "zoomTo(" in body


@pytest.mark.unit
def test_the_wheel_leaves_alone_whatever_it_is_pointed_at() -> None:
    """A long answer and a card opened to `full` have scrollbars of their own, and a wheel that
    zoomed the bench instead of moving the text somebody is reading would be the gesture taking
    priority over the thing it is pointed at. Ctrl overrides that in turn."""
    script = (STATIC / "console.js").read_text()

    assert "function scrollsItself(" in script
    assert "if (!event.ctrlKey && scrollsItself(event.target)) return;" in script


@pytest.mark.unit
def test_nothing_on_the_page_is_smaller_than_twelve_pixels() -> None:
    """A console is read at a glance, across a desk, at the end of a long day. This page had 9px
    and 10px text on it, which is legible on the machine it was written on and nowhere else."""
    css = (STATIC / "console.css").read_text()

    # Text comes off the scale, so a literal size in a `font-size` is how the 9px crept in. The
    # exception is deliberately narrow and it is a *floor*, not a style rule: something set
    # unambiguously large is not what this guards against, and refusing it once blocked making
    # the one glyph that says work is happening big enough to notice. Anything under 2rem must
    # still come from a token.
    raw = re.findall(r"font-size:\s*([0-9.]+)(px|rem)", css)
    small = [
        (size, unit)
        for size, unit in raw
        if not (unit == "rem" and float(size) >= 2) and not (unit == "px" and float(size) >= 32)
    ]
    assert small == [], f"a size that is not on the scale: {small}"

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

    `place` serialises the position of every card on the bench and asks for it to be written down.
    A pointer reports faster than the screen refreshes, so a drag was doing that work and a full
    rebuild of the tie layer per event, most of it thrown away before it was ever painted.
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


@pytest.mark.unit
def test_one_field_finds_anything_on_the_board() -> None:
    """Ctrl+K. Three columns, six kinds of card and a dozen buttons is a discovery problem that
    more buttons do not solve.

    The one thing worth pinning about it: it searches what the page is *already showing*. A
    palette that searched a different set from the one on screen would be a palette that disagrees
    with the page it sits on — so no fetch, and the kinds it looks in are named here.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "function openPalette(" in console and "const PALETTE_ROWS" in console
    assert "event.key.toLowerCase() === 'k'" in console, "nothing opens it"

    finder = console[console.index("function everythingOnThePage(") :]
    finder = finder[: finder.index("\n}\n")]
    assert "fetch(" not in finder, "the palette asks the server instead of reading the page"

    rows = console[console.index("const PALETTE_ROWS") :]
    rows = rows[: rows.index("];")]
    for kind in ("idea", "blocker", "session", "project"):
        assert f"'{kind}'" in rows, f"the palette cannot find a {kind}"


@pytest.mark.unit
def test_the_keyboard_panel_lists_the_keys_that_exist() -> None:
    """A shortcut nobody can discover is a shortcut nobody uses, and a panel that has fallen
    behind the file it documents is worse than none — it is a list of things that do not work."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    keys = console[console.index("const KEYS = `") :]
    keys = keys[: keys.index("`;")]

    assert "Ctrl+K" in keys, "the palette is not discoverable"
    assert "↓" in keys, "moving a card by keyboard is not written down anywhere"


@pytest.mark.unit
def test_a_card_stays_in_the_next_message_until_somebody_switches_it_off() -> None:
    """ "Если активна — следующий запрос собирает в одну группу все активные карточки."

    Sending used to spend every card that went: the bench was cleared of context by the act of
    asking, so a follow-up about the same four cards meant dragging them all back. Active is a
    standing state of the card now, and the only thing that changes it is a person.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "function activeCards(" in console

    submit = console[console.index("document.getElementById('ask').addEventListener('submit'") :]
    submit = submit[: submit.index("\n});")]
    assert "classList.add('spent')" not in submit, (
        "sending still switches the cards off, so the bench empties itself of context"
    )
    assert "activeCards()" in submit


@pytest.mark.unit
def test_what_goes_out_with_a_question_is_a_copy_of_the_bench_not_the_bench() -> None:
    """ "Это должны быть копии карточек на верстаке."

    A record made of the live cards is a record that changes when somebody moves one. The copies
    are the snapshot, and they get names of their own — two nodes answering to `session:abc` would
    have the layout, the ties and the message targets all picking whichever came back first.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    ring = console[console.index("function ringWhatWentWithIt(") :]
    ring = ring[: ring.index("\n}\n")]
    assert "cloneNode(true)" in ring, "the originals are put in the ring rather than copied"
    assert "held${groups}-${index}" in ring, "a copy answers to the same name as its original"
    assert "'copy', 'ringed'" in ring, (
        "a copy is not marked as a record, so it would be carried into the next question too"
    )


@pytest.mark.unit
def test_a_finished_group_becomes_one_card_with_its_own_lines() -> None:
    """ "Та общая обводка после исполнения должна становиться отдельной цельной собирательной
    карточкой на верстаке со своими взаимосвязями и блоками вывода."

    A hatched outline around four copies is the right picture of work in progress and the wrong
    picture of work that is finished — four cards' worth of bench to say one thing happened.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "function collect(" in console
    done = console[console.index("function ringDone(") :]
    done = done[: done.index("\n}\n")]
    assert "collect(ring)" in done, "the ring is left on the bench as a ring"

    made = console[console.index("function collect(") :]
    made = made[: made.index("\n}\n")]
    assert "'pin collection'" in made
    assert "copy.remove()" in made, "the copies are left behind under the new card"
    assert "'asked about'" in made, "the collection has no line to what it was asked with"
    assert "classList.add('ringed')" in made, (
        "a collection would be carried into the next question, which is a conversation reading "
        "its own transcript back to itself"
    )


@pytest.mark.unit
def test_the_answer_finds_the_collection_once_the_copies_are_gone() -> None:
    """The line from an answer pointed at four nodes that no longer existed, so it was not drawn.

    This is the one piece of bookkeeping the collapse creates, and it is invisible when it is
    wrong: the answer simply floats unconnected.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "function nowCollected(" in console
    assert "wentWith.set(id, (wentWith.get(id) || []).map(nowCollected))" in console


@pytest.mark.unit
def test_the_gear_is_big_enough_to_notice_and_stops_for_anybody_who_asked() -> None:
    """ "Кстати давай сделаем её больше." It is the one thing on the bench that says work is
    happening right now, and at text size it was a character you had to look for."""
    css = (STATIC / "console.css").read_text(encoding="utf-8")

    gear = css[css.index(".ring .ring-gear {") :]
    gear = gear[: gear.index("}")]
    found = re.search(r"font-size:\s*([0-9.]+)rem", gear)
    assert found and float(found.group(1)) >= 2, "the gear is still text-sized"
    assert "animation:" in gear, "it does not turn, so a finished ring looks like a working one"
    assert "prefers-reduced-motion" in css, "it turns for somebody who asked it not to"


@pytest.mark.unit
def test_a_copy_does_not_overwrite_the_position_of_the_card_it_copies() -> None:
    """A copy carries the same kind and id as its original, so anything keying a card by those
    two has the copy's position land on the original's row — which moves a card somebody put
    somewhere, silently, the moment they ask a question about it.

    The layout, the lines and the frames all go through `cardName`, so it is the one place this
    can be got right.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    name = console[console.index("function cardName(") :]
    name = name[: name.index("\n}\n")]
    assert "dataset.name ||" in name, (
        "a card is keyed by kind:id, so a copy and its original share one entry in the layout"
    )


@pytest.mark.unit
def test_the_pool_can_be_searched_and_the_field_survives_the_stream() -> None:
    """A column of a hundred and eighty can be ordered and not searched, which is the right tool
    for twenty and the wrong one for two hundred.

    The field is outside `#idea-list` because that element is replaced wholesale every time
    anything changes — a field rendered inside it would lose what somebody had typed mid-word —
    and the filter is re-applied after every one of those replacements, or the first stream tick
    undoes the search.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    board = (TEMPLATES / "board.html").read_text(encoding="utf-8")

    assert 'id="idea-find"' in board
    before, after = board.split('<div id="idea-list"', 1)
    assert 'id="idea-find"' in before, (
        "the search field is inside the list it filters, so the stream replaces it as you type"
    )
    assert "function filterIdeas(" in console
    assert console.count("filterIdeas()") >= 3, (
        "the filter is not re-applied after the column is replaced"
    )


@pytest.mark.unit
def test_a_search_matches_a_card_on_its_own_words_not_its_children_s() -> None:
    """`textContent` on a group holds every card under it, so searching for a child's words would
    light up the parent — a hit reported on the wrong thought."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    body = console[console.index("function filterIdeas(") :]
    body = body[: body.index("\n}\n")]
    assert "dataset.label" in body
    assert ":scope >" in body, "a card is matched on the text of everything inside it"
    assert "card.contains(hit)" in body, (
        "a group whose child matches is hidden, so the way to the match disappears with it"
    )


@pytest.mark.unit
def test_several_cards_can_be_chosen_and_acted_on_together() -> None:
    """On a bench of twelve the alternative is twelve presses, which is how a bench ends up with
    cards nobody switched off because it was not worth the effort.

    Never on a plain drag: that gesture pans, and taking away one somebody already has in their
    hands to add this one would be a bad trade. Shift and drag has always done it, and there is now
    a button that arms it for one sweep — a gesture with no control is one only its author finds.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    board = (TEMPLATES / "board.html").read_text(encoding="utf-8")

    assert "function chosenCards(" in console
    assert 'id="chosen-bar"' in board
    assert 'data-tool="area"' in board, "the area tool has no control"
    for many in ("out", "fold", "off", "none"):
        assert f'data-many="{many}"' in board, f"the bar cannot {many}"

    band = console[
        console.index("if (event.button !== 0 || !(event.shiftKey || tool === 'area'))") :
    ]
    band = band[: band.index("\n});")]
    assert "onBareBench(event.target)" in band, "a drag that began on a card draws a band"

    # And the same press does not also pan: both handlers are on the canvas, and when both ran the
    # surface slid away under the band while it was being drawn.
    assert "!(event.shiftKey || tool === 'area')) {" in console


@pytest.mark.unit
def test_a_chosen_card_carries_the_rest_of_the_choice_when_it_moves() -> None:
    """Choosing six cards and dragging one of them apart from the other five is not what choosing
    them meant."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    together = console[console.index("function alsoMoving(") :]
    together = together[: together.index("\n}\n")]
    assert "chosen" in together
    assert together.index("chosen") < together.index("'.ring'"), (
        "the ring wins over the selection, so a band drawn around a ringed card moves the ring "
        "rather than the band"
    )


@pytest.mark.unit
def test_the_bench_has_a_map_drawn_from_the_same_coordinates_as_the_cards() -> None:
    """Past a dozen cards the bench is bigger than its window, and zooming out until nothing can
    be read is not a way of finding anything.

    Drawn from `placed` rather than by measuring the page: those are the coordinates the cards are
    laid out from, so the map cannot disagree with the bench — and a card that is off the edge has
    no box on screen to measure in the first place.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    board = (TEMPLATES / "board.html").read_text(encoding="utf-8")

    assert 'id="bench-map"' in board and "data-map" in board
    drawn = console[console.index("function drawMap(") :]
    drawn = drawn[: drawn.index("\n}\n")]
    assert "placed.get(" in drawn, "the map measures the page instead of reading the layout"
    assert "getBoundingClientRect" in drawn, "the map does not show where the window is"
    assert "map-here" in drawn


@pytest.mark.unit
def test_a_workbench_can_be_saved_and_come_back() -> None:
    """A set of cards gathered for one piece of work was gathered by hand every time. In this
    browser, beside the column widths and the tab order, and for the same reason: a layout says
    nothing about the ideas themselves — it is where *this person* likes them."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    board = (TEMPLATES / "board.html").read_text(encoding="utf-8")

    assert 'data-add="keep"' in board and 'id="bench-saved"' in board
    for named in ("function keepBench(", "async function openBench(", "function forgetBench("):
        assert named in console, f"{named} is missing"

    what = console[console.index("function benchNow(") :]
    what = what[: what.index("\n}\n")]
    assert "spent" in what and "view" in what, (
        "a saved workbench forgets which cards were switched off or how far they were open, so "
        "coming back to it is not coming back to it"
    )
    assert ":not(.copy):not(.collection)" in what, (
        "the record of an earlier question is saved as part of the working set"
    )


@pytest.mark.unit
def test_the_saved_list_is_rebuilt_whenever_the_menu_opens() -> None:
    """A list kept in step by hand is a list that offers a workbench somebody deleted."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    show = console[console.index("function showMenu(") :]
    show = show[: show.index("\n}\n")]
    assert "showBenches()" in show


@pytest.mark.unit
def test_a_panel_the_page_has_switched_off_stays_off() -> None:
    """`hidden` is an attribute, and the browser implements it as `[hidden] { display: none }` — a
    rule of the very lowest weight, which *any* `display` in this stylesheet beats.

    Every panel here is a flex or grid container, so every one of them ignored being hidden: the
    process panel, the words panel, the run bar and the selection bar were all on screen at once
    on a console where nobody had opened any of them. Found by looking at it.
    """
    css = (STATIC / "console.css").read_text(encoding="utf-8")

    assert "[hidden] { display: none !important; }" in css
    # At the top, before anything that could have been written after it without noticing.
    assert css.index("[hidden]") < css.index(".desk-grid {")


@pytest.mark.unit
def test_a_folded_card_gives_its_name_a_line_of_its_own() -> None:
    """ "Во многих блоках не видно названия и текста в свёрнутом виде."

    The head had grown to eight things on one line 260 pixels wide, with the card's own name last,
    so every card on a bench read `Action work step 1 a li…` and not one said what it was. The fix
    is an order rather than a smaller font: the name and the close button on the first line,
    everything that describes the card on the second, the sentence saying what it does under both.
    """
    css = (STATIC / "console.css").read_text(encoding="utf-8")

    assert ".pin-head { flex-wrap: wrap;" in css, "the head cannot wrap, so something is cut off"
    label = css[css.rindex(".pin-label {") :]
    label = label[: label.index("}")]
    assert "order: -2" in label, "the name is not first on the head"


@pytest.mark.unit
def test_nothing_inside_a_card_scrolls_sideways() -> None:
    """A card you have to scroll sideways to read is a card you do not read. Most of it came from
    one place: a default-width `<input>` is wider than the card it is in."""
    css = (STATIC / "console.css").read_text(encoding="utf-8")

    assert ".pin-body { overflow-x: hidden; }" in css
    assert ".pin-body input, .pin-body select, .pin-body textarea {" in css
    assert ".pin-body .card-facts { grid-template-columns: 1fr; }" in css, (
        "a two-column fact list with a path in it is wider than any card"
    )


@pytest.mark.unit
def test_a_card_never_shows_its_own_id_as_its_name() -> None:
    """A card put on the bench by something that did not know its name — a template being used, a
    sketch being placed — arrived with none, and the head then showed a raw id. An identifier is
    the one thing a card's name must never be."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    step = (TEMPLATES / "_card_step.html").read_text(encoding="utf-8")

    assert "function nameItProperly(" in console
    assert 'data-label="{{ card.label }}"' in step


@pytest.mark.unit
def test_the_scripts_and_styles_are_stamped_with_what_is_in_them() -> None:
    """Without it a browser holds the last stylesheet it saw and keeps rendering from it — which
    it did. The stamp is the content, not the clock, so an unchanged file keeps its URL and stays
    cached, which is the whole point of caching it."""
    from agent_desk.web.routes import _stamped

    stamped = _stamped("console.css")
    assert stamped.startswith("/static/console.css?v=")
    assert _stamped("console.css") == stamped, "the same file got two different stamps"
    # A missing file is a page that says so, not a page that will not render.
    assert _stamped("nothing-here.css") == "/static/nothing-here.css"


@pytest.mark.unit
def test_a_card_put_away_is_not_on_the_bench() -> None:
    """A card folded away with the conversation is still in the document — that is how it comes
    back — and every count, every line and every reading of the bench as a process was including
    it.

    What that looked like on a real console: a corner of the surface filled with lines going to
    nothing, a panel reporting seven steps that have not said what they need about cards nobody
    can see, and "carrying 39 cards" under a bench showing seven.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    assert "function onBench(" in console, "there is no one answer to what is on the bench"
    assert "function showing(" in console, "a line can still be drawn to a card nobody can see"

    # The rule is that a line is never drawn to a card nobody can see. How it is said changed when
    # `drawTies` stopped looking each end up on its own — the cards are gathered once now, and the
    # folded-away ones are left out of that set — so this asserts the rule rather than the call it
    # used to be made with.
    ties = console[console.index("function drawTies(") :]
    ties = ties[: ties.index("\n}\n")]
    assert "put-away" in ties, "a line can be drawn to a card folded away with the conversation"
    assert "pins.get(tie.from)" in ties and "pins.get(tie.to)" in ties, (
        "the ends of a line no longer come from the set that leaves the folded-away cards out"
    )

    # The same markup catches the same mistake twice. A block card renders every idea that message
    # recorded, and each of those lines carries `data-kind="idea"` so it can be dragged out of the
    # answer onto the bench — so a selector without `.pin` in front of it counts the conversation
    # as well as the workbench. It is why `pin` never made a card of an idea, and it is why the
    # console offered to "get started on these 168" under a workbench of twenty-six.
    targets = console[console.index("function syncTargets(") :]
    targets = targets[: targets.index("\n}\n")]
    assert '\'.pin[data-kind="idea"]' in targets, (
        "the count of ideas on the bench includes the idea lines inside the answers"
    )

    for asks in ("pinnedTargets", "activeCards"):
        body = console[console.index(f"function {asks}(") :]
        body = body[: body.index("\n}\n")]
        assert ":not(.put-away)" in body, (
            f"{asks} carries cards that have been folded away into the next message"
        )


@pytest.mark.unit
def test_folding_the_conversation_puts_away_what_the_conversation_brought() -> None:
    """Folding only the block cards left every idea those blocks had written still on the surface.
    On a real console that is thirty-odd cards nobody dropped there, with the process being drawn
    invisible among them.

    A card somebody put there by hand stays — that is the distinction, and it is recorded when the
    card arrives rather than guessed at when the fold happens.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    css = (STATIC / "console.css").read_text(encoding="utf-8")

    assert "holder.dataset.brought = 'yes'" in console, (
        "nothing records that a card came from the conversation rather than from a person"
    )
    fold = console[console.index("function foldConversation(") :]
    fold = fold[: fold.index("\n}\n")]
    assert 'data-brought="yes"' in fold
    assert ".pin.put-away { display: none; }" in css, (
        "a card put away is merely dimmed, so it is still taking a place on the surface"
    )


@pytest.mark.unit
def test_a_choice_is_the_context_when_there_is_one() -> None:
    """ "Щёлкать мышкой по карточкам… после чего мои запросы обрабатываются только с тем контекстом
    что я выбрал."

    The bench used to be "everything except what you switched off", so asking about three cards
    out of thirty meant switching off twenty-seven. Choosing three and asking is the same gesture
    as choosing three and moving them, which is why this is not a mode with a switch of its own.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    carried = console[console.index("function pinnedTargets(") :]
    carried = carried[: carried.index("\n}\n")]
    assert "chosenCards()" in carried, "a selection does not change what the message carries"
    assert "chosen.length" in carried, "there is no fallback to the whole bench"

    # And choosing something has to tell the field, or the change is invisible until the next tick.
    shown = console[console.index("function showChosen(") :]
    shown = shown[: shown.index("\n}\n")]
    assert "syncTargets()" in shown


@pytest.mark.unit
def test_in_the_message_and_working_now_are_not_two_shades_of_one_thing() -> None:
    """ "Блоки что сейчас выполняются… были отличны от блоков которые подсвечиваются как
    участвующие в контексте запросов."

    Two different facts — "this will go with the next message" and "an agent is working on this
    right now" — and on a bench where things are moving, two shades of one highlight read as one
    thing. So they get different kinds of mark: a dot at rest for one, a moving edge for the other.
    """
    css = (STATIC / "console.css").read_text(encoding="utf-8")

    working = css[css.index('.pin[data-step="going"] {') :]
    working = working[: working.index("}")]
    assert "animation:" in working, "a card being worked on does not move, so it reads as a colour"
    assert "repeating-linear-gradient" in working

    # The one that means "in the message" is a dot, and it is not animated.
    dot = css[css.index("\n.pin-live {") :]
    dot = dot[: dot.index("}")]
    assert "animation" not in dot
    assert "prefers-reduced-motion" in css


@pytest.mark.unit
def test_what_a_message_carries_is_cards_and_not_everything_inside_them() -> None:
    """A bench showing seven cards was sending a hundred and twenty-three targets.

    `[data-kind]` matched every element carrying that attribute *inside* a card as well — the idea
    lines a block card lists — so every message went out with every idea ever mentioned in the
    conversation attached to it. Silently, because the count beside the field measures `.pin` and
    the targets did not.

    The same mistake `pin()` made once, for the same reason: `[data-kind]` is not a card.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    carried = console[console.index("function pinnedTargets(") :]
    carried = carried[: carried.index("\n}\n")]

    assert "'.pin[data-kind]" in carried, "the message carries elements that are not cards"
    assert "querySelectorAll('[data-kind]" not in carried


@pytest.mark.unit
def test_a_snapshot_of_sixty_cards_is_a_block_and_not_a_line() -> None:
    """A row is what a group of four folded cards wants to be and what a group of sixty cannot be:
    sixty in a line is seventeen thousand pixels, and the smallest zoom this console has still put
    twelve of them on screen. Found by bringing the group into view and watching it arrive as a
    sliver."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    start = console.index("function ringWhatWentWithIt(")
    body = console[start : console.index("\n}\n", start)]

    assert "Math.ceil(Math.sqrt(went.length))" in body
    assert "index % across" in body and "Math.floor(index / across)" in body


@pytest.mark.unit
def test_a_name_that_did_not_fit_can_be_read_without_opening_the_card() -> None:
    """`.pin-label` is one line with an ellipsis, which is right — a wrapping head makes every card
    taller than the thing it describes. What was wrong is that the half that went off the end could
    only be read by opening the card, and a bench of thirty-seven is thirty-seven presses to find
    out what is in front of you.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    body = console[console.index("function sayTheWholeName(") :]
    body = body[: body.index("\n}\n")]
    assert "scrollWidth" in body and "clientWidth" in body, (
        "the whole name is offered whether or not any of it was cut off"
    )
    assert "removeAttribute('title')" in body, (
        "a label that fits keeps a tooltip repeating what is already on the screen"
    )


@pytest.mark.unit
def test_the_whole_name_is_measured_on_hover_and_not_while_the_bench_is_built() -> None:
    """`scrollWidth` makes the browser settle the layout before it can answer.

    Asked once per card as a bench is written it is the read-after-write loop
    `tests/unit/test_bench_speed.py` exists about — 35 cards were enough to make a pan drop frames.
    Asked when the pointer arrives it is one read on one element, after everything has settled.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    called = [
        line
        for line in console.splitlines()
        if "sayTheWholeName(" in line and "function" not in line
    ]

    assert len(called) == 1, f"the measurement is made from {len(called)} places, not one"
    where = console.index("sayTheWholeName(label)", console.index("addEventListener('pointerover'"))
    listener = console[console.rindex("pins?.addEventListener", 0, where) : where]
    assert "'pointerover'" in listener, "the measurement is not on a pointer event"
    assert "closest?.('.pin-label')" in listener, (
        "the listener is bound per card rather than delegated, so a card added later has no name"
    )


@pytest.mark.unit
def test_the_workbench_can_be_searched_and_the_field_survives_a_redraw() -> None:
    """The pool has had `find a thought…` since it held twenty rows. The bench holds more cards
    than the pool holds ideas and had nothing — and every other control on that row acts on the
    surface as a whole, so none of them answers "where is the card I put down ten minutes ago".

    The field is outside `#pins` for the reason `#idea-find` is outside `#idea-list`: that element
    is replaced whenever the surface changes, and a field inside it loses what somebody had typed
    mid-word.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    board = (TEMPLATES / "board.html").read_text(encoding="utf-8")

    assert 'id="bench-find"' in board
    before, _ = board.split('<div id="pins"', 1)
    assert 'id="bench-find"' in before, (
        "the search field is inside the surface it filters, so a redraw takes what was typed"
    )
    assert "function filterBench(" in console
    ties = console[console.index("function drawTies(") :]
    ties = ties[: ties.index("\n}\n")]
    assert "filterBench()" in ties, (
        "the filter is not re-applied after the lines are drawn again, so the first redraw undoes "
        "the search and a card that arrived during one was never looked at"
    )


@pytest.mark.unit
def test_a_search_over_the_bench_moves_nothing_and_hides_nothing() -> None:
    """Two rules, and both are what makes this a search rather than a rearrangement.

    The arrangement is the thing somebody built and the reason they can find anything at all, so a
    search may not lay the matches out in a row. And the cards that did not match go quiet rather
    than away: the shape of a bench is part of what is read, and a search that empties the surface
    answers a question nobody asked.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    css = (STATIC / "console.css").read_text(encoding="utf-8")

    body = console[console.index("function filterBench(") :]
    body = body[: body.index("\n}\n")]
    assert "classList.toggle('unmatched'" in body
    for moving in ("placeAt(", "settleOverlaps(", "layOut(", "style.left", "style.top"):
        assert moving not in body, f"a search moves the cards ({moving})"

    quiet = css[css.index(".pin.unmatched {") :]
    quiet = quiet[: quiet.index("}")]
    assert "display: none" not in quiet, "a card that did not match is taken off the bench"
    assert "opacity" in quiet
    assert ".pin.unmatched:hover" in css, (
        "a card that did not match cannot be read or pressed, so two thirds of the bench went inert"
    )


@pytest.mark.unit
def test_a_card_is_found_by_what_a_person_can_see_on_it() -> None:
    """`pin.textContent` sweeps in every control on the head, so a bench would light up on
    "press", "brief" and "a line" — this console's words, not the card's."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    body = console[console.index("function benchWords(") :]
    body = body[: body.index("\n}\n")]

    assert ".pin-label" in body and ".pin-body" in body and "dataset.kind" in body
    assert "pin.textContent" not in body, (
        "the haystack is the whole card, so every card matches this console's own button labels"
    )


@pytest.mark.unit
def test_a_line_is_no_louder_than_its_quieter_end() -> None:
    """A bright line running into a card that has gone quiet reads as the line pointing at
    something, which is the opposite of what it means once a search is on."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    css = (STATIC / "console.css").read_text(encoding="utf-8")

    ties = console[console.index("function drawTies(") :]
    ties = ties[: ties.index("\n}\n")]
    assert "path.dataset.from" in ties and "path.dataset.to" in ties, (
        "a line does not say which cards it runs between, so nothing can quieten it with them"
    )
    assert "label.dataset.from" in ties, "the word on a line stays loud while the line goes quiet"

    body = console[console.index("function filterBench(") :]
    body = body[: body.index("\n}\n")]
    assert "[data-from]" in body
    assert ".tie.unmatched" in css and ".tie-label.unmatched" in css


@pytest.mark.unit
def test_a_few_cards_can_be_held_in_front_and_the_rest_set_aside() -> None:
    """Between "leave everything where it is" and "take them all off" there was nothing.

    Somebody whose next twenty minutes are about six cards wants the other thirty-one out of the
    way and still there, and the only control for reducing what is in front of them was the
    destructive one — with undo as the only way back, which is why nobody presses it twice.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    board = (TEMPLATES / "board.html").read_text(encoding="utf-8")

    assert 'data-many="hold"' in board, "there is no way to hold a few cards in front"
    assert 'id="bench-aside"' in board, (
        "a bench holding back eleven cards with nothing saying so has lost them"
    )
    assert "function holdTheseCards(" in console
    assert "function bringBackWhatWasSetAside(" in console

    body = console[console.index("function holdTheseCards(") :]
    body = body[: body.index("\n}\n")]
    assert "put-away" in body, (
        "setting a card aside invents a second kind of hidden, so the eight places that already "
        "know what `put-away` means do not apply to it"
    )
    for moving in ("placeAt(", "settleOverlaps(", "style.left", "remove()"):
        assert moving not in body, (
            f"holding a few cards in front moves or destroys the rest ({moving})"
        )


@pytest.mark.unit
def test_folding_the_conversation_does_not_hand_back_a_card_set_aside() -> None:
    """`foldConversation` toggles `put-away` over the conversation's own cards. Without a reason
    recorded on the card, unfolding would return a card somebody had deliberately put out of the
    way — the console undoing a decision on their behalf."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    body = console[console.index("function foldConversation(") :]
    body = body[: body.index("\n}\n")]

    assert "dataset.aside" in body, (
        "unfolding the conversation gives back cards that were set aside"
    )
    assert body.index("dataset.aside") < body.index("classList.toggle('put-away'"), (
        "the card is toggled before the reason it went away is looked at"
    )


@pytest.mark.unit
def test_the_bench_says_which_cards_are_completely_underneath_another() -> None:
    """A card fully covered by another is indistinguishable from a card that was never added, and
    what somebody does about that is put down a second copy of it.

    Placement avoids collisions, but cards are also dragged by hand, restored from a saved
    workbench and laid out again — and any of those can leave one exactly on top of another.
    """
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    board = (TEMPLATES / "board.html").read_text(encoding="utf-8")

    assert 'id="bench-under"' in board
    body = console[console.index("function markWhatIsUnderneath(") :]
    body = body[: body.index("\n}\n")]
    assert "cards.slice(n + 1)" in body, (
        "a card is reported as hidden by one painted before it, which is the one underneath"
    )
    # Containment, not overlap: half a card is still a card somebody can see and press.
    for edge in (
        "<= under.at.x",
        "<= under.at.y",
        ">= under.at.x + under.w",
        ">= under.at.y + under.h",
    ):
        assert edge in body, f"an overlap is being read as a card that has gone missing ({edge})"


@pytest.mark.unit
def test_what_is_underneath_is_worked_out_from_sizes_already_measured() -> None:
    """`offsetHeight` asked for again after the lines have been written is the read-after-write
    `tests/unit/test_bench_speed.py` exists about — it cost `syncTargets` 36.8ms a frame on 35
    cards. `drawTies` measures every card before it writes anything; this reuses that."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    body = console[console.index("function markWhatIsUnderneath(") :]
    body = body[: body.index("\n}\n")]
    assert "offsetWidth" not in body and "offsetHeight" not in body, (
        "the sizes are measured a second time, after the lines were written"
    )
    assert "getBoundingClientRect" not in body

    ties = console[console.index("function drawTies(") :]
    ties = ties[: ties.index("\n}\n")]
    assert "markWhatIsUnderneath(pins)" in ties, (
        "nothing works out what is hidden, so the chip says whatever it last said"
    )


@pytest.mark.unit
def test_moving_the_hidden_cards_out_leaves_the_visible_arrangement_alone() -> None:
    """The difference between this and `tidy up`: one of them is somebody's arrangement and the
    other is a card that has effectively gone missing inside it."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")

    where = console.index("document.getElementById('bench-under')")
    press = console[where : console.index("\n});\n", where)]

    assert "for (const pin of underneath)" in press, (
        "the press moves cards that were not the ones nobody could see"
    )
    assert "querySelectorAll('.pin" not in press, "the press reaches every card on the bench"


@pytest.mark.unit
def test_the_gate_asks_whether_the_script_runs_and_not_only_whether_it_parses() -> None:
    """`node --check` parses. A file that parses can still stop dead on its first line of
    *execution* — a `const` read before its declaration, a helper called before it exists — and the
    page then looks exactly the way it looks after a syntax error: everything renders, nothing
    works, and no Python test can see it.

    That is not hypothetical. A listener wired to `canvas` three hundred lines above where `canvas`
    is declared was one line from shipping in this repository, and `node --check` was green on it.
    """
    check = (STATIC / ".." / ".." / ".." / "scripts" / "check-the-script.sh").resolve()
    runner = check.parent / "the-script-runs.js"

    assert runner.exists(), "nothing asks whether the console's script reaches its own last line"
    assert runner.name in check.read_text(), "the run check is not wired into the gate"

    said = runner.read_text(encoding="utf-8")
    assert "getElementById" in said and "make()" in said, (
        "an element the stub answers `null` for tests this program's handling of a missing "
        "element rather than the order it does things in"
    )
    assert "setTimeout" in said, (
        "a pending timer keeps node alive after the only question here has been answered"
    )
