# ADR 0004 — the on-disk format is not a contract, so it lives behind one parser

**Status:** accepted · 2026-09-02

## Context

Everything this tool knows comes from files Claude Code writes for itself:
`~/.claude/sessions/*.json` and `~/.claude/projects/**/*.jsonl`. Their shapes are recorded in
[03-session-observation.md](../03-session-observation.md) as verified against CLI `2.1.251`.

Nobody published them. Nobody promised them. A CLI update can change a field name, split a line
type, or move the directory, and it will not announce it.

## Decision

Every read of those files goes through `agent_desk/observe/`. Every shape depended on is captured
in `tests/fixtures/` from a real file, with the producing CLI `version` recorded beside it. The
reader checks the observed `version` against the fixtures' and reports a mismatch as a visible
banner on the board.

**Amended 2026-09-03, after the first machine to run this had two CLI versions live at once: the
check is direction-sensitive.** A version *newer* than the recording, or one that does not parse as
a version at all, raises the banner. An older one does not, because the machine keeps sessions
alive for days — so after any update there is always one, and a banner that is always lit is a
banner nobody reads. An older shape that no longer fits the model raises the field-level notice
instead, which names what moved and is the better signal anyway
([03-session-observation.md](../03-session-observation.md), "Fixtures").

No other module parses those files. No other module is given a raw line.

## Why

The failure being designed against is not "the format changes" — that is expected. It is **the
format changing quietly**: `d.get("status")` returns `None` at five call sites, every one of them
falls back to something reasonable, and the board shows a plausible, wrong picture. A status board
that is confidently wrong is worse than one that is down, because the whole product is that you can
trust it at a glance.

One parser converts that into a single loud failure with a name on it. Fixtures recorded from real
files rather than written by hand are what make the failure loud: a hand-written fixture encodes
what the author believed the format was, and it keeps passing after the format has moved.

The precedent is in the author's other repository, whose model adapter is tested against
`tests/fixtures/claude_result.json`, recorded from a real run for exactly this reason. That is a
pattern worth copying and not a library worth sharing
([adr/0001](0001-a-separate-repository.md)).

## Consequences

- A CLI upgrade may break the board. The intended experience is: the board shows a banner naming
  the field that moved, and the fix is one module and one re-recorded fixture.
- Re-recording a fixture is a normal task with a normal review, not an emergency.
- **A fixture is recorded from the author's own machine and passes through redaction before it is
  committed.** A transcript fixture keeps its structure and loses its content
  ([07-security.md](../07-security.md)).
- The version check is advisory, never a block. A tool that refuses to start because the CLI was
  upgraded has chosen the wrong failure.
- **A backward mismatch is not reported at all**, not even quietly. The case it would catch and the
  field-level notice would not — a field that keeps its name and type and changes its meaning —
  exists in the forward direction too, which is exactly where the banner is kept. Buying a second
  permanent line on the board to half-cover it in one direction is the trade this amendment
  refuses.
