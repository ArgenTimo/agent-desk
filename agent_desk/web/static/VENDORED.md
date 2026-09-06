# What is in here that this project did not write

One file, and it is here rather than fetched from a CDN for the reason
[`adr/0003`](../../../docs/adr/0003-sqlite-and-one-process.md) gives: a local tool that needs the
network to render a list of five sessions has lost the argument. A console you open when something
has gone wrong is a console that has to work when the something is your connection.

| File | What it is | Version | SHA-256 |
|---|---|---|---|
| `htmx.min.js` | [htmx](https://htmx.org), the whole library | `2.0.4` | `e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447` |

## How it got here, and how to replace it

Not "downloaded". Fetched from **two independent mirrors of the npm package** — unpkg and jsdelivr
— and kept only because their bytes were identical. One CDN can serve you anything; two serving
the same 50,917 bytes is a much harder thing to arrange.

`tests/unit/test_static.py` asserts the file is present and still hashes to the value above, so a
corrupted copy, a truncated checkout or a swapped file fails the gate rather than the browser.

To move to a new version: fetch it from both mirrors, check the digests match each other, put the
file here, and update the version and the hash in this table *and* in the test. The test failing is
the point — a vendored dependency that can be replaced without anybody noticing is not vendored,
it is just old.

## Why the whole library and not a smaller thing

`agent_desk/web/static/console.js` already does the common half itself: a form with `hx-post` and
`hx-target` posts and swaps without htmx, which is why the console works with this file missing and
says so in a banner rather than breaking. What it does not do is `hx-get`, `hx-on` and
`hx-trigger` — eight places that fall back to a whole-page navigation.

Writing those three as well would be re-implementing htmx badly, in a file nobody reviews, to avoid
a dependency that is one audited file with no dependencies of its own. So: the library, vendored,
pinned and hashed.
