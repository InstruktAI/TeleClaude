.PHONY: help install launchers launchers-renew-authority deepseek-stack link format lint test clean dev start stop restart kill status cron-smoke release-runner-install release-runner-start release-runner-start-observe release-runner-start-shadow release-runner-start-canary release-runner-stop release-runner-status

CRON_SMOKE_SINCE ?= 15m
RELEASE_RUNNER_MODE ?= authority
RELEASE_RUNNER_CANARY_SCOPE ?=
RELEASE_RUNNER_CANARY_PROFILE ?=
export RELEASE_RUNNER_MODE RELEASE_RUNNER_CANARY_SCOPE RELEASE_RUNNER_CANARY_PROFILE
LEGACY_ACTIVATION ?= 0
STOP_OUTCOME_FILE ?=

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
	@LEGACY_ACTIVATION="$(LEGACY_ACTIVATION)" STOP_OUTCOME_FILE="$(STOP_OUTCOME_FILE)" ./bin/daemon-control.sh stop

restart:
	@LEGACY_ACTIVATION="$(LEGACY_ACTIVATION)" ./bin/daemon-control.sh restart

kill:
	@./bin/daemon-control.sh kill

status:
	@./bin/daemon-control.sh status

cron-smoke:
	@CRON_SMOKE_SINCE="$(CRON_SMOKE_SINCE)" tools/make/cron-smoke.sh

release-runner-install:
	@uv run python -m tools.ci.release_runner install

release-runner-start:
	@uv run python -m tools.ci.release_runner start --mode "$(RELEASE_RUNNER_MODE)"

release-runner-start-observe:
	@uv run python -m tools.ci.release_runner start --mode observe

release-runner-start-shadow:
	@uv run python -m tools.ci.release_runner start --mode shadow

release-runner-start-canary:
	@uv run python -m tools.ci.release_runner start --mode canary --canary-scope "$$RELEASE_RUNNER_CANARY_SCOPE" --canary-profile "$$RELEASE_RUNNER_CANARY_PROFILE"

release-runner-stop:
	@uv run python -m tools.ci.release_runner stop --mode "$(RELEASE_RUNNER_MODE)"

release-runner-status:
	@uv run python -m tools.ci.release_runner status --mode "$(RELEASE_RUNNER_MODE)"
