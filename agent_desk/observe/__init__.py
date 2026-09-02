"""The only module that parses what Claude Code writes to disk.

Nothing outside this package receives a raw line or a raw dict from `~/.claude/`. The formats are
internal state that nobody promised, so they live behind one parser tested against fixtures
recorded from real files — docs/adr/0004-the-transcript-format-is-not-a-contract.md.

Read-only, always: the correctness claim of the whole tool is that an observed session cannot tell
this ran.
"""
