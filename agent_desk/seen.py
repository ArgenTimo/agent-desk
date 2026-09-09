"""What the page actually is, as text, for a reader with no browser.

*«Три настоящих дефекта — рамка против панорамирования, перетаскивание как клик, "carry nothing",
стиравшая верстак — прожили в коде часы и нашлись за пять минут, как только появился браузер. Всё
это время у меня был исходник и не было продукта.»*

Not a screenshot. An accessibility tree and the list of what can be pressed is enough to catch the
three things reading the source does not catch: a control that is not on the page at all, a control
that is on it and bound to nothing, and a script that fell over on load.

## Why a tree of roles and names, and not the markup

Markup is what the source already says. What a reader needs is what a person would find: a heading
that says this, a button that says that, a region called something. So every element is reduced to
the role a browser would give it and the name a screen reader would read out, and everything
carrying neither is dropped — a `div` inside a `div` is layout, and layout is what makes a page
unreadable as text.

## Dead controls

«Контрол, который ничего не делает при нажатии, хуже отсутствующего.» A button is bound if it
submits a form, posts through HTMX, carries a handler attribute, or is reached by the console's own
script through its id or one of its classes. A button that is none of those is listed as dead, and
being listed is the whole of what happens: this says what it found, and a person decides whether it
is a defect or a control the script reaches some way this does not model.

## A ceiling

«Страница целиком — это не ответ.» The board is a few hundred elements on a quiet morning. What did
not fit is named as a number so a reader knows there is more, which is the difference between a
short page and a truncated one.
"""

from __future__ import annotations

import html.parser
import json
import re
from collections import Counter
from dataclasses import dataclass, field

# How much of a tree there may be. A page of four hundred lines is a page nobody reads as text, and
# the point of this is to be read.
MOST_LINES = 200

MORE = "… and {left} more that did not fit."

# How many controls are listed. Far more than a page should have, and a page with more than this is
# itself the finding.
MOST_CONTROLS = 120

# What a browser calls these. Only the ones that carry meaning: a `div` has no role, which is why a
# tree of them is not a tree.
ROLES = {
    "a": "link",
    "article": "article",
    "aside": "complementary",
    "button": "button",
    "footer": "contentinfo",
    "form": "form",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "header": "banner",
    "input": "input",
    "label": "label",
    "li": "listitem",
    "main": "main",
    "nav": "navigation",
    "ol": "list",
    "option": "option",
    "select": "combobox",
    "table": "table",
    "textarea": "textbox",
    "ul": "list",
}

# What can be pressed. Everything else on a page is something to read.
PRESSED = {"a", "button", "input", "select", "textarea"}

# Elements that never close. Treating one as open is how a tree ends up two hundred levels deep
# with every later element nested inside an `<input>` — which is what this produced first, and it
# read as a page nobody could have built.
NEVER_CLOSES = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

# Attributes that mean "this does something when you press it". `hx-` is HTMX's, which is how most
# of this console's controls are wired; `on…` is a handler written into the markup.
BOUND = ("href", "onclick", "onchange", "oninput", "onsubmit", "formaction")


@dataclass(frozen=True)
class Node:
    """One element a person would find, as a browser would describe it."""

    role: str
    name: str
    deep: int
    # What it is in this program's markup, so a reader can go and look at it.
    tag: str = ""
    id: str = ""

    def as_line(self) -> str:
        said = "  " * self.deep + self.role
        if self.name:
            said += f' "{self.name}"'
        if self.id:
            said += f" #{self.id}"
        return said


@dataclass(frozen=True)
class Control:
    """One thing that can be pressed, and what it is bound to."""

    tag: str
    name: str
    id: str = ""
    bound: str = ""
    # What the markup calls it, so a class the script reaches it by can be recognised.
    classes: tuple[str, ...] = ()
    # The `data-…` attributes it carries. This console wires most of its controls through them and
    # a delegated listener, so a model that did not know about them would call half the page dead.
    marks: tuple[str, ...] = ()
    # What the elements around it are called. A delegated handler reaches a button through
    # `event.target.closest('.tab')` — the button carries nothing and is still bound, and a check
    # that only looked at the button itself would report a chat tab as dead. It is.
    around: tuple[str, ...] = ()

    @property
    def dead(self) -> bool:
        return not self.bound

    def as_line(self) -> str:
        who = f'{self.tag} "{self.name}"' + (f" #{self.id}" if self.id else "")
        return f"{who} — {self.bound or 'NOTHING PRESSES IT'}"


@dataclass
class _Reader(html.parser.HTMLParser):
    """The page, walked once, producing both answers."""

    nodes: list[Node] = field(default_factory=list)
    controls: list[Control] = field(default_factory=list)
    _deep: int = 0
    _open: list[tuple[str, int]] = field(default_factory=list)
    _text: list[str] = field(default_factory=list)
    _skip: int = 0
    # What every element still open is called, innermost last, as selectors.
    _around: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(convert_charrefs=True)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        said = {name: (value or "") for name, value in attrs}
        if tag in ("script", "style"):
            self._skip += 1
            return
        # Hidden from a browser is hidden from this: a tree that lists what nobody can see is a
        # tree that disagrees with the screen.
        if "hidden" in said or said.get("aria-hidden") == "true":
            return
        if tag not in NEVER_CLOSES:
            self._around.append((tag, _handles(said)))
        role = said.get("role") or ROLES.get(tag, "")
        if role and tag not in NEVER_CLOSES:
            self.nodes.append(
                Node(
                    role=role,
                    name=_named(said),
                    deep=self._deep,
                    tag=tag,
                    id=said.get("id", ""),
                )
            )
            self._open.append((tag, self._deep))
            self._deep += 1
        elif role:
            # On the tree but not a level of it: nothing is ever inside an `<input>`.
            self.nodes.append(
                Node(role=role, name=_named(said), deep=self._deep, tag=tag, id=said.get("id", ""))
            )
        if tag in PRESSED:
            self.controls.append(
                Control(
                    tag=tag,
                    name=_named(said),
                    id=said.get("id", ""),
                    bound=_bound(tag, said),
                    classes=tuple(said.get("class", "").split()),
                    marks=tuple(one for one in said if one.startswith("data-")),
                    around=tuple(handle for _, handles in self._around[:-1] for handle in handles),
                )
            )
        self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if self._around and self._around[-1][0] == tag:
            self._around.pop()
        # Only tags this pushed. A `</div>` used to walk the stack looking for a `div` that was
        # never on it and empty the whole thing, after which every later element was nested inside
        # whatever came before — a tree that read as a page nobody could have built.
        if self._open and self._open[-1][0] == tag:
            _, deep = self._open.pop()
            self._deep = deep
            said = " ".join("".join(self._text).split())[:80]
            if said and not self.nodes[-1].name:
                # A heading's name is its text, and its text arrives after the tag opens.
                self.nodes[-1] = Node(
                    role=self.nodes[-1].role,
                    name=said,
                    deep=self.nodes[-1].deep,
                    tag=self.nodes[-1].tag,
                    id=self.nodes[-1].id,
                )
                if self.controls and self.controls[-1].tag == self.nodes[-1].tag:
                    last = self.controls[-1]
                    self.controls[-1] = Control(
                        tag=last.tag,
                        name=said,
                        id=last.id,
                        bound=last.bound,
                        classes=last.classes,
                        marks=last.marks,
                        around=last.around,
                    )
        self._text = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """`<input />`. It opens and closes at once, which is what `NEVER_CLOSES` already assumes."""
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._text.append(data)


def _named(said: dict[str, str]) -> str:
    """What a screen reader would read out: the label somebody wrote, or the value on a control."""
    for where in ("aria-label", "title", "alt", "placeholder", "value", "name"):
        if said.get(where):
            return said[where][:80]
    return ""


def _bound(tag: str, said: dict[str, str]) -> str:
    """What happens when this is pressed, in one phrase, or nothing."""
    for where in said:
        if where.startswith("hx-") and where not in ("hx-swap", "hx-target", "hx-trigger"):
            return f"{where}={said[where]}"[:80]
    for where in BOUND:
        if said.get(where):
            return f"{where}={said[where]}"[:80]
    if tag in ("input", "select", "textarea"):
        # A field is not a control that does something; it is a control that holds something, and
        # its name is how it gets there.
        return f"a field called {said['name']}" if said.get("name") else ""
    # A `<button>` with no type is a submit button — that is HTML's default and the reason so many
    # of them carry `type="button"` explicitly. One that says `type="button"` is the opposite: it
    # does nothing at all unless something reaches it, which is exactly what this is looking for.
    if said.get("type") == "submit" or (tag == "button" and "type" not in said):
        return "submits the form it is in"
    return ""


def read(page: str, *, script: str = "") -> tuple[list[Node], list[Control]]:
    """Walk one rendered page. `script` is the console's own source, used to decide what is dead."""
    reader = _Reader()
    reader.feed(page)
    reader.close()
    # How many controls wear each class. A class on one element identifies that element; a class on
    # forty of them identifies none of them, and calling all forty bound because the script names
    # the class would be the check saying everything is fine — which is what it replaces.
    worn = Counter(name for one in reader.controls for name in one.classes)
    controls = [
        Control(
            tag=one.tag,
            name=one.name,
            id=one.id,
            bound=one.bound or _reached_by(one, script, worn),
            classes=one.classes,
            marks=one.marks,
            around=one.around,
        )
        for one in reader.controls
    ]
    return reader.nodes, controls


def _reached_by(one: Control, script: str, worn: Counter[str]) -> str:
    """Whether the console's script reaches this control, by its id or by a class only it wears."""
    if one.id and re.search(rf"""['"#]{re.escape(one.id)}['"\s)]""", script):
        return f"the script reaches #{one.id}"
    for name in one.classes:
        if worn[name] == 1 and re.search(rf"""['".]{re.escape(name)}['"\s)]""", script):
            return f"the script reaches .{name}"
    for mark in one.marks:
        # `data-hide` in the markup is `[data-hide]` in a selector and `dataset.hide` in code. A
        # mark is written for the script to find, so naming it either way is the script finding it.
        short = mark.removeprefix("data-")
        camel = re.sub(r"-(.)", lambda m: m.group(1).upper(), short)
        if re.search(rf"\[{re.escape(mark)}[\]=]|dataset\.{re.escape(camel)}\b", script):
            return f"the script reaches [{mark}]"
    for handle in reversed(one.around):
        if _named_in(handle, script):
            return f"the script reaches {handle} around it"
    return ""


def _handles(said: dict[str, str]) -> tuple[str, ...]:
    """What a selector could call this element: its id, its classes, its marks."""
    found = [f"#{said['id']}"] if said.get("id") else []
    found += [f".{one}" for one in said.get("class", "").split()]
    found += [f"[{one}]" for one in said if one.startswith("data-")]
    return tuple(found)


def _named_in(handle: str, script: str) -> bool:
    """Whether the script names this selector — as a string, or as a `dataset` field."""
    if handle.startswith("["):
        mark = handle[1:-1]
        camel = re.sub(r"-(.)", lambda m: m.group(1).upper(), mark.removeprefix("data-"))
        return bool(re.search(rf"\[{re.escape(mark)}[\]=]|dataset\.{re.escape(camel)}\b", script))
    return bool(re.search(rf"""['"]{re.escape(handle)}['"\s)]""", script))


# How many of the page's own errors are kept. A script that throws in a loop throws forever, and a
# list of four hundred identical lines says exactly what the first twenty do.
MOST_ERRORS = 20


def read_what_went_wrong(raw: bytes) -> list[str]:
    """What the page said its script threw, out of the message it posted.

    The parsing is here rather than in the route because this module is the one about what the page
    said, and because the structural rule in `tests/unit/test_structure.py` wants every JSON parse
    outside `observe/` to be a deliberate, named exception. This one is: a message a page posts to
    its own server is a wire protocol the two halves of this program agree on, not one of Claude
    Code's on-disk formats that can change without warning (docs/adr/0004).

    Raises `ValueError` on anything unusable, which the route answers with a 400. A page posting
    nonsense is a bug in this program, and swallowing it would hide the one thing this exists to
    surface.
    """
    said = json.loads(raw)
    if not isinstance(said, dict):
        raise ValueError("that was not an object")
    return [str(one)[:300] for one in (said.get("said") or [])[:MOST_ERRORS]]


def as_text(nodes: list[Node], controls: list[Control], errors: list[str]) -> str:
    """The whole answer: the tree, the controls, and what the script said when it loaded.

    The ceiling falls on the tree and never on the other two. A page with four hundred elements has
    four hundred elements worth of layout and a dozen controls, and the dozen is what somebody is
    looking for — cutting the answer at a fixed number of lines from the top would drop exactly the
    part that is short enough to keep.
    """
    said = [f"{len(nodes)} things on the page.", *within(nodes)]
    said += ["", f"{len(controls)} controls."]
    said += [f"  {one.as_line()}" for one in controls[:MOST_CONTROLS]]
    if len(controls) > MOST_CONTROLS:
        left = len(controls) - MOST_CONTROLS
        said.append("  " + MORE.format(left=left))
    dead = [one for one in controls if one.dead]
    if dead:
        said += [
            "",
            f"{len(dead)} of them {'is' if len(dead) == 1 else 'are'} bound to nothing. A "
            "control that does nothing when it is pressed is worse than one that is not there.",
        ]
    said += ["", "What the script said when the page loaded:"]
    said += [f"  {one}" for one in errors] or ["  nothing"]
    return "\n".join(said)


def within(nodes: list[Node], *, most: int = MOST_LINES) -> list[str]:
    """A ceiling, and what did not fit named as a number.

    The difference between a short page and a truncated one is whether the reader is told, and a
    reader who is not told acts on a page they think they have all of.
    """
    lines = [one.as_line() for one in nodes]
    if len(lines) <= most:
        return lines
    left = len(lines) - most
    return [*lines[:most], MORE.format(left=left)]
