.PHONY: help install launchers launchers-renew-authority deepseek-stack link format lint test clean dev start stop restart kill status cron-smoke

CRON_SMOKE_SINCE ?= 15m
LEGACY_ACTIVATION ?= 0

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

# Daemon control commands (user-friendly aliases)
start:
	@./bin/daemon-control.sh start

stop:
	@LEGACY_ACTIVATION="$(LEGACY_ACTIVATION)" ./bin/daemon-control.sh stop

restart:
	@LEGACY_ACTIVATION="$(LEGACY_ACTIVATION)" ./bin/daemon-control.sh restart

kill:
	@./bin/daemon-control.sh kill

status:
	@./bin/daemon-control.sh status

cron-smoke:
	@CRON_SMOKE_SINCE="$(CRON_SMOKE_SINCE)" tools/make/cron-smoke.sh
