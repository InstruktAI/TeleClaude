.PHONY: help install link certs format lint check-no-unit-tests test-e2e test-meta test coverage coverage-html coverage-report diagrams clean dev start stop restart kill status cron-smoke generate-types pg-up pg-down pg-reset cargo-build cargo-test cargo-lint cargo-fmt

CRON_SMOKE_SINCE ?= 15m

# Default target
help:
	@echo "TeleClaude Development Commands"
	@echo "==============================="
	@echo ""
	@echo "Repo Setup:"
	@echo "  make install      Set up this TeleClaude checkout and install repo dependencies"
	@echo "  telec config wizard  Configure this TeleClaude checkout interactively"
	@echo "  make start        Start daemon via launchd/systemd"
	@echo "  make bootstrap    Non-interactive machine-global bootstrap"
	@echo "  make bootstrap-ci Lean non-interactive bootstrap for CI environments"
	@echo "  make generate-types  Generate TypeScript types from Pydantic API models"
	@echo "  make build-artifacts  Generate and deploy agent artifacts (docs, skills, prompts)"
	@echo "  make link         Link shared scripts/docs into ~/.teleclaude"
	@echo "  make certs        Generate SSL certificates for REST API"
	@echo ""
	@echo "Code Quality:"
	@echo "  make format       Format code with ruff"
	@echo "  make lint                 Run repo-wide linting checks"
	@echo "  make check-no-unit-tests  Verify no forbidden unit tests exist"
	@echo ""
	@echo "Testing:"
	@echo "  make test-e2e         Run integration/e2e tests only"
	@echo "  make test-meta        Run process meta tests (serial, isolated harness)"
	@echo "  make test             Run repo-wide tests"
	@echo "  make coverage         Run tests with coverage report"
	@echo "  make coverage-html    Generate HTML coverage report"
	@echo "  make coverage-report  Open HTML coverage report in browser"
	@echo "  make cron-smoke       List configured jobs and check recent cron runner failures"
	@echo ""
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
	@echo "Installing project dependencies..."
	@bash -eu -o pipefail -c '\
		if ! command -v uv >/dev/null 2>&1; then \
			curl -LsSf https://astral.sh/uv/install.sh | sh; \
			export PATH="$$HOME/.local/bin:$$PATH"; \
		fi; \
		uv run --group dev python -c "print(\"Python environment ready\")"; \
		if [ -d frontend ] && [ -f frontend/package.json ]; then \
			if command -v pnpm >/dev/null 2>&1; then pnpm --dir frontend install --ignore-scripts; else npm --prefix frontend install --ignore-scripts; fi; \
		fi; \
		if [ -f Cargo.toml ]; then \
			if command -v cargo >/dev/null 2>&1; then \
				cargo fetch; \
				cargo build --release -p telec-daemon; \
				target_binary="$$HOME/.local/bin/telec-daemon"; \
				mkdir -p "$$(dirname "$$target_binary")"; \
				cp target/release/telec-daemon "$$target_binary"; \
				chmod +x "$$target_binary"; \
			else \
				echo "cargo not found — skipping telec-daemon build (v2, pre-cutover; becomes required at the v2 cutover)."; \
			fi; \
		fi; \
		hook_dest="$$(git rev-parse --git-path hooks/pre-commit 2>/dev/null || printf ".git/hooks/pre-commit")"; \
		mkdir -p "$$(dirname "$$hook_dest")"; \
		hook_src=".githooks/pre-commit"; \
		if [ ! -f "$$hook_src" ] && [ -f templates/quality/python/.githooks/pre-commit ]; then hook_src="templates/quality/python/.githooks/pre-commit"; fi; \
		if [ -f "$$hook_src" ]; then cp "$$hook_src" "$$hook_dest"; chmod +x "$$hook_dest"; fi; \
	'
	@echo "✓ Project dependencies installed"

link:
	@echo "Linking shared scripts/docs..."
	@mkdir -p "$$HOME/.teleclaude"
	@ln -sfn "$(PWD)/scripts" "$$HOME/.teleclaude/scripts"
	@if [ -e "$$HOME/.teleclaude/docs" ] && [ ! -L "$$HOME/.teleclaude/docs" ]; then rm -rf "$$HOME/.teleclaude/docs"; fi
	@ln -sfn "$(PWD)/docs/global" "$$HOME/.teleclaude/docs"
	@echo "✓ Linked shared scripts/docs"

format:
	@echo "Formatting code..."
	@FILES_FROM="$(FILES_FROM)" bash -eu -o pipefail -c '\
		scoped=0; paths=(); \
		if [ -n "$$FILES_FROM" ]; then scoped=1; while IFS= read -r -d "" path; do paths+=("$$path"); done < "$$FILES_FROM"; fi; \
		run_frontend_format() { if command -v pnpm >/dev/null 2>&1; then pnpm exec prettier --write "$$@"; else npx --yes prettier --write "$$@"; fi; }; \
		run_rust_fmt() { \
			local rust_workspace=0 path dir manifest name; local -a rust_packages=(); local -A rust_seen=(); \
			for path in "$$@"; do \
				if [ "$$path" = "Cargo.toml" ] || [ "$$path" = "Cargo.lock" ]; then rust_workspace=1; continue; fi; \
				case "$$path" in *.rs) ;; *) continue ;; esac; \
				dir="$${path%/*}"; if [ "$$dir" = "$$path" ]; then dir="."; fi; manifest=""; \
				while [ "$$dir" != "." ] && [ "$$dir" != "/" ]; do \
					if [ -f "$$dir/Cargo.toml" ]; then manifest="$$dir/Cargo.toml"; break; fi; \
					dir="$${dir%/*}"; if [ -z "$$dir" ]; then dir="."; fi; \
				done; \
				if [ -z "$$manifest" ]; then continue; fi; \
				if [ "$$manifest" = "Cargo.toml" ]; then rust_workspace=1; continue; fi; \
				name="$$(sed -n -E "/^\\[package\\]/,/^\\[/{s/^[[:space:]]*name[[:space:]]*=[[:space:]]*\"([^\"]+)\".*/\\1/p;}" "$$manifest" | head -n 1)"; \
				if [ -z "$$name" ]; then rust_workspace=1; continue; fi; \
				if [ -z "$${rust_seen[$$name]+x}" ]; then rust_seen[$$name]=1; rust_packages+=("$$name"); fi; \
			done; \
			if [ "$$rust_workspace" -eq 1 ]; then cargo fmt --all; elif [ "$${#rust_packages[@]}" -gt 0 ]; then for name in "$${rust_packages[@]}"; do cargo fmt -p "$$name"; done; fi; \
		}; \
		if [ "$$scoped" -eq 0 ]; then \
			uv run ruff check --fix .; uv run ruff format .; \
			prettier_targets=(); for p in README.md AGENTS.md; do [ -f "$$p" ] && prettier_targets+=("$$p"); done; [ -d docs ] && prettier_targets+=("docs/**/*.md"); [ "$${#prettier_targets[@]}" -gt 0 ] && npx --yes prettier --write "$${prettier_targets[@]}"; \
			if [ -d frontend ] && [ -f frontend/package.json ]; then (cd frontend && run_frontend_format .); fi; \
			if [ -f Cargo.toml ]; then cargo fmt --all; fi; \
		else \
			py=(); prettier_root=(); prettier_frontend=(); rust_inputs=(); \
			for path in "$${paths[@]}"; do \
				case "$$path" in *.py) py+=("$$path") ;; esac; \
				case "$$path" in frontend/*) case "$$path" in *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs|*.json|*.css|*.md|*.yml|*.yaml) prettier_frontend+=("$${path#frontend/}") ;; esac ;; *.md|*.json|*.yml|*.yaml) prettier_root+=("$$path") ;; esac; \
				case "$$path" in *.rs|Cargo.toml|Cargo.lock) rust_inputs+=("$$path") ;; esac; \
			done; \
			[ "$${#py[@]}" -gt 0 ] && uv run ruff check --fix "$${py[@]}" && uv run ruff format "$${py[@]}"; \
			[ "$${#prettier_root[@]}" -gt 0 ] && npx --yes prettier --write "$${prettier_root[@]}"; \
			if [ "$${#prettier_frontend[@]}" -gt 0 ] && [ -d frontend ]; then (cd frontend && run_frontend_format "$${prettier_frontend[@]}"); fi; \
			if [ "$${#rust_inputs[@]}" -gt 0 ] && [ -f Cargo.toml ]; then run_rust_fmt "$${rust_inputs[@]}"; fi; \
		fi; \
	'
	@echo "✓ Code formatted"

lint:
	@echo "Running lint checks..."
	@FILES_FROM="$(FILES_FROM)" bash -eu -o pipefail -c '\
		scoped=0; paths=(); \
		if [ -n "$$FILES_FROM" ]; then scoped=1; while IFS= read -r -d "" path; do paths+=("$$path"); done < "$$FILES_FROM"; fi; \
		run_jscpd() { if [ "$$#" -gt 0 ]; then npx --yes jscpd --min-lines 25 --min-tokens 150 --mode strict --exit-code 1 --ignore "**/migrations/**" "$$@"; fi; }; \
		run_frontend_lint() { if command -v pnpm >/dev/null 2>&1; then pnpm exec eslint "$$@" && pnpm exec tsc --noEmit; else npx --yes eslint "$$@" && npx --yes tsc --noEmit; fi; }; \
		run_rust_clippy() { \
			local rust_workspace=0 path dir manifest name; local -a rust_packages=(); local -A rust_seen=(); \
			for path in "$$@"; do \
				if [ "$$path" = "Cargo.toml" ] || [ "$$path" = "Cargo.lock" ]; then rust_workspace=1; continue; fi; \
				case "$$path" in *.rs|*/Cargo.toml) ;; *) continue ;; esac; \
				if [ "$${path##*/}" = "Cargo.toml" ]; then dir="$${path%/*}"; else dir="$${path%/*}"; fi; \
				if [ "$$dir" = "$$path" ]; then dir="."; fi; manifest=""; \
				while [ "$$dir" != "." ] && [ "$$dir" != "/" ]; do \
					if [ -f "$$dir/Cargo.toml" ]; then manifest="$$dir/Cargo.toml"; break; fi; \
					dir="$${dir%/*}"; if [ -z "$$dir" ]; then dir="."; fi; \
				done; \
				if [ -z "$$manifest" ]; then continue; fi; \
				if [ "$$manifest" = "Cargo.toml" ]; then rust_workspace=1; continue; fi; \
				name="$$(sed -n -E "/^\\[package\\]/,/^\\[/{s/^[[:space:]]*name[[:space:]]*=[[:space:]]*\"([^\"]+)\".*/\\1/p;}" "$$manifest" | head -n 1)"; \
				if [ -z "$$name" ]; then rust_workspace=1; continue; fi; \
				if [ -z "$${rust_seen[$$name]+x}" ]; then rust_seen[$$name]=1; rust_packages+=("$$name"); fi; \
			done; \
			if [ "$$rust_workspace" -eq 1 ]; then cargo clippy --workspace --all-targets -- -D warnings; elif [ "$${#rust_packages[@]}" -gt 0 ]; then for name in "$${rust_packages[@]}"; do cargo clippy -p "$$name" --all-targets -- -D warnings; done; fi; \
		}; \
		if [ "$$scoped" -eq 0 ]; then \
			uv run ruff check .; uv run ruff format --check .; uv run pyright; uv run mypy; \
			jscpd_targets=(); for p in teleclaude tools; do [ -e "$$p" ] && jscpd_targets+=("$$p"); done; run_jscpd "$${jscpd_targets[@]}"; \
			if [ -d frontend ] && [ -f frontend/package.json ]; then (cd frontend && run_frontend_lint .); fi; \
			if [ -f Cargo.toml ]; then cargo clippy --workspace --all-targets -- -D warnings; fi; \
		else \
			py=(); py_full=0; ts=(); ts_full=0; rust_inputs=(); \
			for path in "$${paths[@]}"; do \
				case "$$path" in *.py) py+=("$$path") ;; pyproject.toml|mypy.ini|pyrightconfig.json) py_full=1 ;; esac; \
				case "$$path" in frontend/*.ts|frontend/*.tsx|frontend/*.js|frontend/*.jsx|frontend/*.mjs|frontend/*.cjs) ts+=("$${path#frontend/}") ;; frontend/package.json|frontend/tsconfig*.json|frontend/eslint.config.*|frontend/vitest.config.*) ts_full=1 ;; esac; \
				case "$$path" in *.rs|Cargo.toml|Cargo.lock|*/Cargo.toml) rust_inputs+=("$$path") ;; esac; \
			done; \
			if [ "$$py_full" -eq 1 ]; then uv run ruff check .; uv run ruff format --check .; uv run pyright; uv run mypy; jscpd_targets=(); for p in teleclaude tools; do [ -e "$$p" ] && jscpd_targets+=("$$p"); done; run_jscpd "$${jscpd_targets[@]}"; \
			elif [ "$${#py[@]}" -gt 0 ]; then uv run ruff check "$${py[@]}"; uv run ruff format --check "$${py[@]}"; uv run pyright "$${py[@]}"; uv run mypy "$${py[@]}"; run_jscpd "$${py[@]}"; fi; \
			if [ -d frontend ] && [ -f frontend/package.json ]; then if [ "$$ts_full" -eq 1 ]; then (cd frontend && run_frontend_lint .); elif [ "$${#ts[@]}" -gt 0 ]; then (cd frontend && run_frontend_lint "$${ts[@]}"); fi; fi; \
			if [ "$${#rust_inputs[@]}" -gt 0 ] && [ -f Cargo.toml ]; then run_rust_clippy "$${rust_inputs[@]}"; fi; \
		fi; \
	'
	@echo "✓ Lint checks passed"

check-no-unit-tests:
	@uv run python tools/lint/forbid_unit_tests.py
	@uv run python tools/lint/forbid_ts_unit_tests.py

test-e2e:
	@echo "Running integration/e2e tests..."
	@uv run pytest tests/integration/ -v -m "not expensive"
	@echo "✓ Integration tests passed"

test-agents:
	@echo "Running agent invocation matrix (real LLM calls)..."
	@uv run pytest tests/integration/test_agent_invocation_matrix.py -v -m expensive -o "addopts="
	@echo "✓ Agent matrix tests passed"

test-meta:
	@echo "Running process meta tests (serial, isolated harness)..."
	@uv run pytest tests/process/ -o "addopts=" --timeout=60
	@echo "✓ Process meta tests passed"

test:
	@echo "Running repo-wide tests..."
	@SNAPSHOT_UPDATE="$(SNAPSHOT_UPDATE)" bash -eu -o pipefail -c '\
		pytest_args=(); if [ -n "$$SNAPSHOT_UPDATE" ]; then pytest_args+=("--snapshot-update"); fi; \
		uv run pytest "$${pytest_args[@]}"; \
		run_frontend_test() { if command -v pnpm >/dev/null 2>&1; then pnpm test "$$@"; else npm test "$$@"; fi; }; \
		if [ -d frontend ] && [ -f frontend/package.json ]; then if [ -n "$$SNAPSHOT_UPDATE" ]; then (cd frontend && run_frontend_test -- -u); else (cd frontend && run_frontend_test); fi; fi; \
		if [ -f Cargo.toml ]; then cargo test --workspace --lib; fi; \
	'
	@if [ -z "$$CI" ]; then $(MAKE) test-meta; fi
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

cron-smoke:
	@echo "Listing configured cron jobs..."
	@.venv/bin/python scripts/cron_runner.py --list
	@echo ""
	@echo "Recent cron runner failures (last $(CRON_SMOKE_SINCE))..."
	@instrukt-ai-logs teleclaude --since $(CRON_SMOKE_SINCE) --grep "failed to load job"

bootstrap:
	@./bin/install.sh --yes

bootstrap-ci:
	@./bin/install.sh --ci

onboard:
	@telec onboard

build-artifacts:
	@$(MAKE) generate-types
	@uv run -m teleclaude.cli.telec sync

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
