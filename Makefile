.PHONY: help install launchers link format lint test clean dev start stop restart kill status cron-smoke generate-types

CRON_SMOKE_SINCE ?= 15m

# Default target
help:
	@tools/make/help.sh

install:
	@./bin/install.sh

launchers:
	@src/Launcher/build.sh

link:
	@./bin/init/link_shared_scripts.sh

format:
	@FILES_FROM="$(FILES_FROM)" bash tools/quality.sh format

lint:
	@FILES_FROM="$(FILES_FROM)" bash tools/quality.sh lint

test:
	@echo "No tests in this repository — see docs/project/policy/test-moratorium.md"

clean:
	@tools/make/clean.sh

dev:
	@tools/make/dev.sh

# Daemon control commands (user-friendly aliases)
start:
	@./bin/daemon-control.sh start

stop:
	@./bin/daemon-control.sh stop

restart:
	@./bin/daemon-control.sh restart

kill:
	@./bin/daemon-control.sh kill

status:
	@./bin/daemon-control.sh status

cron-smoke:
	@CRON_SMOKE_SINCE="$(CRON_SMOKE_SINCE)" tools/make/cron-smoke.sh

generate-types:
	@uv run -m teleclaude.codegen.pydantic_to_typescript
