# Every gate has one spelling, and it is a target here. Use these rather than composing the
# underlying command, so that what you ran, what the Stop hook runs, and what CI would run are
# the same thing (CLAUDE.md, "Stack").

.DEFAULT_GOAL := help
PORT ?= 8787
# Deliberately not 0.0.0.0 by default: `make share SHARE_HOST=0.0.0.0` is a sentence somebody has
# to type, and typing it is the moment the security model changes.
SHARE_HOST ?= 127.0.0.1

# Poetry follows an active VIRTUAL_ENV. A shell with another project's venv sourced — which is
# normal when several agents work several repositories on one machine — would otherwise install
# this project's dependencies into that project's environment, and run this project's gate there.
# Discovered the hard way on day one.
POETRY = unset VIRTUAL_ENV VIRTUAL_ENV_PROMPT; poetry
URL  := http://127.0.0.1:$(PORT)

.PHONY: help install gate verify test lint typecheck run share overlay check-links clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Dependencies, dev group included
	$(POETRY) install --with dev

lint: ## ruff
	$(POETRY) run ruff check agent_desk tests scripts
	$(POETRY) run ruff format --check agent_desk tests

typecheck: ## mypy
	$(POETRY) run mypy agent_desk

test: ## pytest -m unit
	$(POETRY) run pytest -m unit -q

gate: lint typecheck test ## What stop-verify.sh runs at every turn end

verify: gate check-links ## Everything green before a human sees it

check-links: ## Prove every relative link in docs/ and design/ resolves
	@scripts/check-doc-links.sh

# --timeout-graceful-shutdown is not a tuning knob, it is a bug fix. Uvicorn's graceful stop waits
# for open responses to finish, and the board's server-sent-events response never finishes by
# design — so Ctrl-C on a running console with a board open hangs forever, and SIGTERM does not
# end it either. Found by killing the server with a browser attached.
run: ## The console on http://127.0.0.1:8787
	$(POETRY) run uvicorn agent_desk.web.app:app --host 127.0.0.1 --port $(PORT) --reload \
	  --timeout-graceful-shutdown 2

# The one target that changes the security model of this tool. Everything else binds to
# loopback, where "anything that can reach the port can already read ~/.claude/" holds; this one
# puts an ideas list on the network, and what protects it is a named link per viewer
# (docs/07-security.md, docs/09-roadmap.md Phase 4).
share: ## The console, plus the shared ideas view on the network
	@echo "the shared ideas list will be reachable on $(SHARE_HOST):8788 — links are minted at $(URL)/viewers"
	AGENT_DESK_SHARE_HOST=$(SHARE_HOST) $(POETRY) run python -m agent_desk

overlay: ## The console in its own window, for a window rule to pin always-on-top
	@browser=$$(command -v google-chrome || command -v chromium || command -v chromium-browser); \
	if [ -z "$$browser" ]; then \
	  echo "No Chromium-family browser found. Open $(URL) yourself, or see docs/06-console.md."; \
	  exit 1; \
	fi; \
	"$$browser" --app=$(URL) --class=agent-desk --user-data-dir=$$HOME/.local/share/agent-desk/browser >/dev/null 2>&1 &

clean: ## Remove caches
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .pytest_cache .ruff_cache
