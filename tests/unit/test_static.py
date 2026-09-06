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
