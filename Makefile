.PHONY: help install init link certs format lint check-test-mapping test-unit test-e2e test coverage coverage-html coverage-report diagrams clean dev start stop restart kill status generate-types pg-up pg-down pg-reset cargo-build cargo-test cargo-lint cargo-fmt

CRON_SMOKE_SINCE ?= 15m

# Default target
help:
	@echo "TeleClaude Development Commands"
	@echo "==============================="
	@echo ""
	@echo "Repo Setup:"
	@echo "  make install      Set up this TeleClaude checkout and install repo dependencies"
	@echo "  make init         Initialize this TeleClaude repo for development (ARGS=-y for unattended)"
	@echo "  make bootstrap    Non-interactive install AND init (for CI)"
	@echo "  make bootstrap-ci Lean non-interactive bootstrap for CI environments"
	@echo "  make generate-types  Generate TypeScript types from Pydantic API models"
	@echo "  make build-artifacts  Generate and deploy agent artifacts (docs, skills, prompts)"
	@echo "  make link         Link shared scripts/docs into ~/.teleclaude"
	@echo "  make certs        Generate SSL certificates for REST API"
	@echo ""
	@echo "Code Quality:"
	@echo "  make format       Format code with ruff"
	@echo "  make lint                 Run repo-wide linting checks"
	@echo "  make check-test-mapping   Check 1:1 source-to-test mapping (expected to fail during overhaul)"
	@echo ""
	@echo "Testing:"
	@echo "  make test-unit        Run unit tests only"
	@echo "  make test-e2e         Run integration/e2e tests only"
	@echo "  make test             Run repo-wide tests"
	@echo "  make coverage         Run tests with coverage report"
	@echo "  make coverage-html    Generate HTML coverage report"
	@echo "  make coverage-report  Open HTML coverage report in browser"
	@echo "Daemon Control:"
	@echo "  make start        Start daemon via launchd"
	@echo "  make stop         Stop daemon AND disable service (emergency only)"
	@echo "  make restart      Restart daemon"
	@echo "  make kill         Kills daemon process (emergency only)"
	@echo "  make status       Check daemon status"
	@echo ""
	@echo "Development:"
	@echo "  make dev          Run daemon in foreground (manual mode)"
	@echo "  make clean        Clean generated files and caches"
	@echo ""

install:
	@./bin/install.sh

init:
	@./bin/init.sh $(ARGS)

link:
	@echo "Linking shared scripts/docs..."
	@mkdir -p "$$HOME/.teleclaude"
	@ln -sfn "$(PWD)/scripts" "$$HOME/.teleclaude/scripts"
	@mkdir -p "$$HOME/.teleclaude/docs"
	@for src in "$(PWD)"/docs/global/*; do \
		entry=$$(basename "$$src"); \
		dst="$$HOME/.teleclaude/docs/$$entry"; \
		case "$$entry" in .* ) continue ;; esac; \
		if [ -L "$$dst" ]; then rm -f "$$dst"; \
		elif [ -d "$$dst" ]; then [ "$$entry" = "third-party" ] && continue; rm -rf "$$dst"; \
		elif [ -f "$$dst" ]; then rm -f "$$dst"; fi; \
		if [ -d "$$src" ] || [ "$$entry" = "baseline.md" ] || [ "$$entry" = "index.yaml" ]; then \
			ln -s "$$src" "$$dst"; \
		fi; \
	done
	@echo "✓ Linked shared scripts/docs"

format:
	@echo "Formatting code..."
	@telec code format --all
	@echo "✓ Code formatted"

lint:
	@echo "Running lint checks..."
	@telec code lint --all
	@echo "✓ Lint checks passed"

check-test-mapping:
	@uv run python tools/lint/test_mapping.py

test-unit:
	@echo "Running unit tests..."
	@uv run pytest tests/unit/ -v
	@echo "✓ Unit tests passed"

test-e2e:
	@echo "Running integration/e2e tests..."
	@uv run pytest tests/integration/ -v -m "not expensive"
	@echo "✓ Integration tests passed"

test-agents:
	@echo "Running agent invocation matrix (real LLM calls)..."
	@uv run pytest tests/integration/test_agent_invocation_matrix.py -v -m expensive -o "addopts="
	@echo "✓ Agent matrix tests passed"

test:
	@echo "Running repo-wide tests..."
	@telec code test --all
	@echo "✓ All tests passed"

coverage:
	@echo "Running tests with coverage..."
	@uv run pytest --cov=teleclaude --cov-report=term-missing --cov-report=html --cov-report=xml --cov-report=json
	@echo ""
	@echo "✓ Coverage report generated"
	@echo "  - Terminal: see above"
	@echo "  - HTML: coverage/html/index.html"
	@echo "  - XML: coverage/coverage.xml"
	@echo "  - JSON: coverage/coverage.json"

coverage-html:
	@echo "Generating HTML coverage report..."
	@uv run pytest --cov=teleclaude --cov-report=html --cov-report=term-missing -q
	@echo "✓ HTML coverage report: coverage/html/index.html"

coverage-report: coverage-html
	@echo "Opening coverage report in browser..."
	@open coverage/html/index.html || xdg-open coverage/html/index.html || echo "Please open coverage/html/index.html manually"

diagrams:
	@echo "Generating architecture diagrams..."
	@mkdir -p docs/diagrams
	@python scripts/diagrams/extract_state_machines.py
	@python scripts/diagrams/extract_events.py
	@python scripts/diagrams/extract_data_model.py
	@python scripts/diagrams/extract_modules.py
	@python scripts/diagrams/extract_commands.py
	@python scripts/diagrams/extract_runtime_matrix.py
	@echo "✓ Architecture diagrams generated in docs/diagrams/"

clean:
	@echo "Cleaning generated files..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@rm -rf .pytest_cache 2>/dev/null || true
	@rm -rf .mypy_cache 2>/dev/null || true
	@rm -rf coverage 2>/dev/null || true
	@rm -f .coverage 2>/dev/null || true
	@rm -rf test_sessions.db 2>/dev/null || true
	@rm -rf *.egg-info 2>/dev/null || true
	@echo "✓ Cleaned generated files"

dev:
	@echo "Starting daemon in foreground (Ctrl+C to stop)..."
	@. .venv/bin/activate && python -m teleclaude.daemon

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

bootstrap:
	@./bin/install.sh --yes

bootstrap-ci:
	@./bin/install.sh --ci

onboard:
	@telec onboard

build-artifacts:
	@$(MAKE) generate-types
	@uv run -m teleclaude.cli.telec sync --warn-only

generate-types:
	@uv run -m teleclaude.codegen.pydantic_to_typescript

# ---------------------------------------------------------------------------
# v2 Rust workspace targets
# ---------------------------------------------------------------------------

pg-up:
	@echo "Starting Postgres + Redis via docker compose..."
	@docker compose up -d postgres redis
	@echo "✓ Postgres + Redis are up"

pg-down:
	@echo "Stopping Postgres + Redis..."
	@docker compose down
	@echo "✓ Containers stopped"

pg-reset:
	@echo "Tearing down Postgres + Redis WITH volumes..."
	@docker compose down -v
	@echo "✓ Containers and volumes destroyed"

cargo-build:
	@echo "Building Rust workspace..."
	@cargo build --workspace
	@echo "✓ cargo build --workspace succeeded"

cargo-test:
	@echo "Running Rust workspace tests..."
	@cargo test --workspace
	@echo "✓ cargo test --workspace succeeded"

test-rust-integration:
	@echo "Running Rust integration suite against docker-compose Postgres + Redis..."
	@$(MAKE) pg-up
	@PGPASSWORD=postgres psql -U postgres -h localhost -d teleclaude -c "DROP SCHEMA IF EXISTS workflow CASCADE;" >/dev/null 2>&1 || true
	@PGPASSWORD=postgres psql -U postgres -h localhost -d teleclaude -f crates/workflow/migrations/0001_init.sql >/dev/null
	@DATABASE_URL=postgres://postgres:postgres@localhost:5432/teleclaude \
	 REDIS_URL=redis://localhost:6379 \
	 TELECLAUDE_OWNER_EMAIL=ci@example.com \
	 cargo test --workspace -- --ignored --test-threads=1
	@echo "✓ Rust integration suite passed"

cargo-lint:
	@echo "Running cargo clippy..."
	@cargo clippy --workspace --all-targets -- -D warnings
	@echo "✓ cargo clippy succeeded"

cargo-fmt:
	@echo "Formatting Rust code..."
	@cargo fmt --all
	@echo "✓ cargo fmt complete"
