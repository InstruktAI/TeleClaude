.PHONY: help install link format lint check-no-unit-tests test-e2e test-agents test-meta test coverage coverage-html coverage-report diagrams clean dev start stop restart kill status cron-smoke build-artifacts generate-types

CRON_SMOKE_SINCE ?= 15m

# Default target
help:
	@tools/make/help.sh

install:
	@./bin/install.sh

link:
	@./bin/init/link_shared_scripts.sh

format:
	@FILES_FROM="$(FILES_FROM)" bash tools/quality.sh format

lint:
	@FILES_FROM="$(FILES_FROM)" bash tools/quality.sh lint

check-no-unit-tests:
	@tools/make/tests.sh check-no-unit-tests

test-e2e:
	@tools/make/tests.sh e2e

test-agents:
	@tools/make/tests.sh agents

test-meta:
	@tools/make/tests.sh meta

test:
	@SNAPSHOT_UPDATE="$(SNAPSHOT_UPDATE)" bash tools/quality.sh test

coverage:
	@tools/make/coverage.sh run

coverage-html:
	@tools/make/coverage.sh html

coverage-report:
	@tools/make/coverage.sh report

diagrams:
	@tools/make/diagrams.sh

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

build-artifacts:
	@tools/make/build-artifacts.sh

generate-types:
	@uv run -m teleclaude.codegen.pydantic_to_typescript
