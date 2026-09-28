#!/usr/bin/env bash
#
# prod.sh — the working console, as a copy of a tag rather than the checkout being edited (A2).
#
#   scripts/prod.sh install <tag>   clone origin into $PROD_DIR at <tag>, install, start the unit
#   scripts/prod.sh update  <tag>   move that copy to <tag>, reinstall, restart
#   scripts/prod.sh unit            print the systemd --user unit this installs
#
# Why a copy: the working console used to be `make run --reload` in the checkout that sessions
# commit into, so every edit restarted it and every branch's migrations reached the live database
# (_research/04_dogfooding_gaps.md, R3). A tag is a decision to update; a saved file is not.
#
# The database is not copied or touched here: it stays in ~/.local/share/agent-desk, and the
# migration runner copies it to agent-desk.db.bak-v<N> before applying anything new
# (agent_desk/store/migrate.py). Rolling back is `update <previous tag>` plus that file.
set -euo pipefail

PROD_DIR="${AGENT_DESK_PROD_DIR:-$HOME/opt/agent-desk-prod}"
UNIT_NAME=agent-desk.service
UNIT_FILE="$HOME/.config/systemd/user/$UNIT_NAME"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

unit() {
  cat <<EOF
[Unit]
Description=agent-desk console (the working one, from $PROD_DIR)
After=default.target

[Service]
WorkingDirectory=$PROD_DIR
# The CLI the board reads and the answer engine asks is found here, not in a login shell's PATH.
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
# No --reload: this copy changes only when \`prod.sh update\` moves it to another tag.
ExecStart=$PROD_DIR/.venv/bin/python -m agent_desk
# always, not on-failure: uvicorn exits 0 on SIGTERM, and a console that a stray pkill ends for
# good is not a console you can trust to be there. \`systemctl --user stop\` still stops it.
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF
}

install_deps() {
  (cd "$PROD_DIR" && unset VIRTUAL_ENV VIRTUAL_ENV_PROMPT \
    && POETRY_VIRTUALENVS_IN_PROJECT=true PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
       poetry install --only main --quiet)
}

at_tag() {
  git -C "$PROD_DIR" fetch --quiet --tags origin
  git -C "$PROD_DIR" -c advice.detachedHead=false checkout --quiet "refs/tags/$1"
}

case "${1:-}" in
  unit)
    unit
    ;;
  install)
    tag="${2:?usage: prod.sh install <tag>}"
    [ -e "$PROD_DIR" ] && { echo "$PROD_DIR exists — use: prod.sh update <tag>" >&2; exit 1; }
    git clone --quiet --no-checkout "$(git -C "$HERE" remote get-url origin)" "$PROD_DIR"
    at_tag "$tag"
    install_deps
    mkdir -p "$(dirname "$UNIT_FILE")"
    unit > "$UNIT_FILE"
    systemctl --user daemon-reload
    systemctl --user enable --now "$UNIT_NAME"
    echo "agent-desk $tag running from $PROD_DIR — systemctl --user status $UNIT_NAME"
    ;;
  update)
    tag="${2:?usage: prod.sh update <tag>}"
    [ -d "$PROD_DIR/.git" ] || { echo "no copy at $PROD_DIR — use: prod.sh install <tag>" >&2; exit 1; }
    was="$(git -C "$PROD_DIR" describe --tags --exact-match 2>/dev/null || git -C "$PROD_DIR" rev-parse --short HEAD)"
    at_tag "$tag"
    install_deps
    unit > "$UNIT_FILE"
    systemctl --user daemon-reload
    systemctl --user restart "$UNIT_NAME"
    echo "agent-desk $was -> $tag; back: prod.sh update $was (and the .bak-v<N> beside the database if a migration ran)"
    ;;
  *)
    sed -n '3,7p' "$0" >&2
    exit 2
    ;;
esac
