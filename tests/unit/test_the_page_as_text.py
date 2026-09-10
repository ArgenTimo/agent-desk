"""An agent sees the built product without a browser (01M21KTYFADJZ27H4EPVZ736CX).

«Три настоящих дефекта — рамка против панорамирования, перетаскивание как клик, "carry nothing",
стиравшая верстак — прожили в коде часы и нашлись за пять минут, как только появился браузер.»
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
from agent_desk import seen
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]


def _tree(page: str, script: str = "") -> str:
    nodes, controls = seen.read(page, script=script)
    return seen.as_text(nodes, controls, [])


# --- the tree ------------------------------------------------------------------------------------
def test_it_reads_roles_and_names_rather_than_markup() -> None:
    """What a reader needs is what a person would find, not what the source already says."""
    nodes, _ = seen.read(
        '<main><h1>the board</h1><button aria-label="hide the overview">×</button></main>'
    )

    assert [(one.role, one.name) for one in nodes] == [
        ("main", ""),
        ("heading", "the board"),
        ("button", "hide the overview"),
    ]


def test_layout_is_not_in_the_tree() -> None:
    """A div inside a div is layout, and layout is what makes a page unreadable as text."""
    nodes, _ = seen.read("<div><div><span>x</span></div></div>")

    assert nodes == []


def test_an_element_that_never_closes_is_not_a_level() -> None:
    """Nothing is ever inside an `<input>`. Treating one as open nested every later element under
    it, and the tree read as a page nobody could have built."""
    nodes, _ = seen.read('<form><input name="a"><button>go</button></form>')

    assert [one.deep for one in nodes] == [0, 1, 1]


def test_an_end_tag_for_something_that_was_never_opened_leaves_the_tree_alone() -> None:
    """`</div>` used to walk the stack looking for a div that was never on it and empty the whole
    thing, after which every later element was nested inside whatever came before."""
    nodes, _ = seen.read("<main><div><h1>one</h1></div><h2>two</h2></main>")

    assert [(one.role, one.deep) for one in nodes] == [
        ("main", 0),
        ("heading", 1),
        ("heading", 1),
    ]


def test_what_a_browser_hides_this_hides() -> None:
    """A tree that lists what nobody can see is a tree that disagrees with the screen."""
    nodes, _ = seen.read('<main><h1 hidden>gone</h1><h2 aria-hidden="true">also</h2></main>')

    assert [one.role for one in nodes] == ["main"]


# --- the controls --------------------------------------------------------------------------------
def test_a_control_bound_to_nothing_is_named() -> None:
    """ "Контрол, который ничего не делает при нажатии, хуже отсутствующего.\" """
    _, controls = seen.read('<div><button type="button">press me</button></div>')

    (one,) = controls
    assert one.dead
    assert "NOTHING PRESSES IT" in one.as_line()


def test_the_ways_a_control_is_bound() -> None:
    said = (
        '<a href="/ideas">the inbox</a>'
        '<button hx-post="/x">post</button>'
        '<form><button type="submit">send</button></form>'
        '<input name="answer">'
    )

    _, controls = seen.read(said)

    assert [one.dead for one in controls] == [False, False, False, False]


def test_the_script_reaching_it_by_id_counts_as_bound() -> None:
    said = '<div><button type="button" id="tidy">tidy up</button></div>'

    _, controls = seen.read(said, script="document.getElementById('tidy')")

    assert not controls[0].dead


def test_a_class_only_one_control_wears_counts_and_a_shared_one_does_not() -> None:
    """A class on one element identifies that element; a class on forty identifies none of them,
    and calling all forty bound would be this check saying everything is fine."""
    alone = '<div><textarea class="words-in"></textarea></div>'
    many = '<div><button type="button" class="pin"></button><button type="button" class="pin"></button></div>'
    script = "panel.querySelector('.words-in'); surface.querySelectorAll('.pin')"

    _, one = seen.read(alone, script=script)
    _, two = seen.read(many, script=script)

    assert not one[0].dead
    assert all(control.dead for control in two)


# --- the size limit ------------------------------------------------------------------------------
def test_the_whole_page_is_not_an_answer() -> None:
    """ "Ограничение размера: страница целиком — это не ответ." And what did not fit is a number,
    because a reader who is not told acts on a page they think they have all of."""
    said = _tree("<main>" + "<h1>a heading</h1>" * 400 + "</main>")

    assert len([line for line in said.splitlines() if line.startswith("  heading")]) <= (
        seen.MOST_LINES
    )
    assert "more that did not fit" in said


def test_the_ceiling_never_falls_on_the_controls() -> None:
    """A page with four hundred elements has a dozen controls, and the dozen is what somebody is
    looking for — cutting from the top would drop exactly the part short enough to keep."""
    said = _tree("<main>" + "<h1>a heading</h1>" * 400 + '<a href="/ideas">the inbox</a></main>')

    assert "the inbox" in said
    assert "What the script said when the page loaded" in said


# --- what the script said ------------------------------------------------------------------------
async def test_the_page_hands_back_what_its_script_threw() -> None:
    """ "Ошибки скрипта собираются на странице и отдаются вместе с ним." The source cannot show a
    script that fell over: the page still renders and every gesture on it is silently gone."""
    routes.SCRIPT_SAID.clear()

    class Posted:
        async def body(self) -> bytes:
            return json.dumps({"said": ["x is not defined (console.js:12)"]}).encode()

    await routes.the_script_fell_over(Posted())

    assert routes.SCRIPT_SAID == ["x is not defined (console.js:12)"]
    assert "x is not defined" in seen.as_text([], [], routes.SCRIPT_SAID)
    routes.SCRIPT_SAID.clear()


async def test_something_that_is_not_json_is_refused_rather_than_stored() -> None:
    class Posted:
        async def body(self) -> bytes:
            return b"not json"

    assert (await routes.the_script_fell_over(Posted())).status_code == 400


def test_a_page_whose_script_said_nothing_says_nothing() -> None:
    assert "nothing" in seen.as_text([], [], [])


def test_the_page_collects_its_own_errors_before_anything_can_throw() -> None:
    """A handler installed after the line that throws catches nothing, and the errors worth
    catching are the ones at the top."""
    script = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))

    assert code.index("addEventListener('error'") < code.index("const poll")
    assert "/seen/errors" in code


# --- and the gate --------------------------------------------------------------------------------
def test_the_gate_checks_that_the_console_script_parses() -> None:
    """ "Неразобранный скрипт убивает всю страницу разом, и ни один питоновский тест этого не
    видит." One command, and it is in `verify`."""
    makefile = (HERE / "Makefile").read_text(encoding="utf-8")

    assert "check-script" in makefile.split("verify:")[1].splitlines()[0]
    assert (HERE / "scripts" / "check-the-script.sh").exists()


def test_the_console_script_parses() -> None:
    """The same check the gate runs, so a red gate and a red test say the same thing. Skipped
    where node is not installed rather than passing quietly: a check that succeeds without its
    tool reports green about something nobody looked at (CLAUDE.md, rule five)."""
    script = HERE / "agent_desk" / "web" / "static" / "console.js"
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on this machine")
    try:
        done = subprocess.run(  # noqa: S603 — a fixed argv, and the only variable in it is a
            # path inside this repository
            [node, "--check", str(script)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        pytest.skip("node is not on this machine")

    assert done.returncode == 0, done.stderr


def test_a_delegated_handler_on_an_ancestor_counts_as_bound() -> None:
    """A chat tab carries nothing at all and is still bound: the script reaches it through
    `event.target.closest('.tab')`. A check that looked only at the button would call every tab on
    the page dead, and a list of ninety false findings is a list nobody reads."""
    said = '<div class="tab" data-thread="x"><button type="button" class="tab-name">chat 4</button></div>'

    _, controls = seen.read(said, script="event.target.closest('.tab')")

    assert not controls[0].dead
    assert ".tab" in controls[0].as_line()


def test_an_ancestor_the_script_never_names_does_not_rescue_it() -> None:
    said = '<div class="somewhere"><button type="button">press me</button></div>'

    _, controls = seen.read(said, script="event.target.closest('.tab')")

    assert controls[0].dead


def test_the_console_has_no_control_bound_to_nothing() -> None:
    """The point of the whole thing, run against the page it was written for. A control that fails
    this is either a defect or a wiring this module does not model — and both are worth a look."""
    page = (HERE / "agent_desk" / "web" / "templates" / "board.html").read_text(encoding="utf-8")
    script = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")

    _, controls = seen.read(page, script=script)

    assert [one.as_line() for one in controls if one.dead] == []


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json at all",
        b"[]",
        b"5",
        b"null",
        b'{"said": 5}',
        b'{"said": "one message, not a list of them"}',
        b'{"said": {"a": 1}}',
    ],
)
def test_a_page_posting_a_shape_this_cannot_read_is_a_four_hundred(raw: bytes) -> None:
    """ "Raises `ValueError` on anything unusable, which the route answers with a 400" is the whole
    of the contract between this and `the_script_fell_over`, which catches that and nothing else.

    Three shapes left by another door: `{"said": 5}` as a `TypeError`, `{"said": {…}}` as a
    `KeyError`, and a bare string as a list of its own characters — eight letters read as eight
    things a script threw. A page posting nonsense is a bug in this program and a 500 hides it,
    which is the opposite of what this whole module is for.
    """
    with pytest.raises(ValueError):
        seen.read_what_went_wrong(raw)


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        (b"{}", []),
        (b'{"said": null}', []),
        (b'{"said": []}', []),
        (b'{"said": [null, 5, {}]}', ["None", "5", "{}"]),
        (b'{"said": ["TypeError: x is not a function"]}', ["TypeError: x is not a function"]),
    ],
)
def test_what_a_page_can_post_it_reads(raw: bytes, want: list[str]) -> None:
    """A page with nothing to report says so, and the entries are stringified rather than trusted
    to be strings — the script posts what a browser handed it."""
    assert seen.read_what_went_wrong(raw) == want


def test_a_page_that_threw_more_than_anybody_will_read_is_cut() -> None:
    thrown = json.dumps({"said": [f"error {n}" for n in range(500)]}).encode()

    assert len(seen.read_what_went_wrong(thrown)) == seen.MOST_ERRORS
