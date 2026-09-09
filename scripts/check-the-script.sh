#!/usr/bin/env bash
# Does the console's script parse at all?
#
# "«Неразобранный скрипт убивает всю страницу разом, и ни один питоновский тест этого не видит.»"
# A syntax error in console.js does not fail one control — it stops the file executing, so every
# gesture, every hotkey and the whole workbench go at once, and the page still renders. Nothing in
# a Python suite can see that, and it is one command to check.
#
# Node is not a dependency of this project and never becomes one: it is asked whether it is there,
# and a machine without it is told so rather than passed silently. A check that quietly succeeds
# when its tool is missing is worse than no check, because the gate then reports green about
# something nobody looked at (CLAUDE.md, rule five).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="$here/agent_desk/web/static/console.js"

if ! command -v node >/dev/null 2>&1; then
  echo "node is not on this machine, so $script was NOT checked."
  echo "Install node, or run 'node --check' on it wherever you have one."
  exit 0
fi

node --check "$script"
echo "console.js parses."
