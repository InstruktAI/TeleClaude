.PHONY: help install launchers launchers-renew-authority deepseek-stack link format lint test clean dev start stop restart kill status cron-smoke

CRON_SMOKE_SINCE ?= 15m
LEGACY_ACTIVATION ?= 0
STOP_OUTCOME_FILE ?=
# Where the platform's installation lives (install.sh and teleclaude/core/reconciliation/installation.py agree).
INSTALLATION_ROOT := $(or $(XDG_DATA_HOME),$(HOME)/.local/share)/instrukt-ai/teleclaude

# Default target
help:
	@tools/make/help.sh

install:
	@./bin/install.sh

launchers:
	@.venv/bin/python -m teleclaude.install.launcher_identity --intent build --project-root "$(CURDIR)"

launchers-renew-authority:
	@.venv/bin/python -m teleclaude.install.launcher_identity --intent renew --project-root "$(CURDIR)"

deepseek-stack:
	@.venv/bin/python -m teleclaude.install.deepseek_stack

link:
	@./bin/init/link_shared_scripts.sh

format:
	@FILES_FROM="$(FILES_FROM)" bash tools/quality.sh format

lint:
	@FILES_FROM="$(FILES_FROM)" bash tools/quality.sh lint

test:
	@echo "No tests in this repository — see docs/local/policy/test-moratorium.md"

clean:
	@tools/make/clean.sh

dev:
	@tools/make/dev.sh

# Daemon control commands (user-friendly aliases). The lifecycle belongs to the installation, not to the
# checkout this Makefile sits in: each verb delegates to the installed `telec app`, and `kill` — the explicit
# forced recovery `telec app` does not carry — to the installation's own lifecycle script.
start:
	@telec app start

stop:
	@LEGACY_ACTIVATION="$(LEGACY_ACTIVATION)" STOP_OUTCOME_FILE="$(STOP_OUTCOME_FILE)" telec app stop

restart:
	@LEGACY_ACTIVATION="$(LEGACY_ACTIVATION)" telec app restart

kill:
	@"$(INSTALLATION_ROOT)/current/bin/daemon-control.sh" kill

status:
	@telec app status

cron-smoke:
	@CRON_SMOKE_SINCE="$(CRON_SMOKE_SINCE)" tools/make/cron-smoke.sh

