# For a human

Ordered by importance. Each item: what, why, exact commands, which task it depends on.

## H1 · Stop hook: keep it on (depends on A1 — done)
The research recommended switching `stop-verify.sh` off until the suite was hermetic. It is on in
`.claude/settings.json` and nothing in `~/.claude/settings.json` disables it. After A1 (#14) a
`make gate` starts no `claude` and never opens `~/.local/share/agent-desk/` (verified: 0 calls
from a fake `claude`, live DB mtime unchanged). If you turned it off anywhere in your own
environment, turn it back on; there is nothing to change in the repository.
