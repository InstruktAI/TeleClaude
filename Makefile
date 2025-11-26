.PHONY: help install init certs format lint test-unit test-e2e test-all test coverage coverage-html coverage-report clean dev start stop restart kill status

# Default target
help:
	@echo "TeleClaude Development Commands"
	@echo "==============================="
	@echo ""
	@echo "Setup:"
	@echo "  make install      Install dependencies"
	@echo "  make init         Run installation wizard (ARGS=-y for unattended)"
	@echo "  make certs        Generate SSL certificates for REST API"
	@echo ""
	@echo "Code Quality:"
	@echo "  make format       Format code with black and isort"
	@echo "  make lint         Run linting checks (pylint, mypy)"
	@echo ""
	@echo "Testing:"
	@echo "  make test-unit        Run unit tests only"
	@echo "  make test-e2e         Run integration/e2e tests only"
	@echo "  make test-all         Run all tests"
	@echo "  make test             Alias for test-all"
	@echo "  make coverage         Run tests with coverage report"
	@echo "  make coverage-html    Generate HTML coverage report"
	@echo "  make coverage-report  Open HTML coverage report in browser"
	@echo ""
	@echo "Daemon Control:"
	@echo "  make start        Start daemon via launchd"
	@echo "  make stop         Stop daemon (disables service)"
	@echo "  make restart      Restart daemon"
	@echo "  make kill         Kills daemon (won't stop mcp server, so very messy)"
	@echo "  make status       Check daemon status"
	@echo ""
	@echo "Development:"
	@echo "  make dev          Run daemon in foreground (manual mode)"
	@echo "  make clean        Clean generated files and caches"
	@echo ""

install:
	@echo "Installing dependencies..."
	python3 -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt
	. .venv/bin/activate && pip install -r requirements-test.txt
	@echo "✓ Dependencies installed"
	@echo ""
	@echo "Next step: Run 'make init' to set up the service (or 'make init ARGS=-y' for unattended mode)"

init:
	@echo "Running installation wizard..."
	@./install.sh $(ARGS)

format:
	@echo "Formatting code..."
	@./bin/format.sh
	@echo "✓ Code formatted"

lint:
	@echo "Running lint checks..."
	@./bin/lint.sh
	@echo "✓ Lint checks passed"

test-unit:
	@echo "Running unit tests..."
	@. .venv/bin/activate && pytest tests/unit/ -v --timeout=1
	@echo "✓ Unit tests passed"

test-e2e:
	@echo "Running integration/e2e tests..."
	@. .venv/bin/activate && pytest tests/integration/ -v --timeout=5
	@echo "✓ Integration tests passed"

test-all:
	@echo "Running all tests..."
	@./bin/test.sh
	@echo "✓ All tests passed"

test: test-all

coverage:
	@echo "Running tests with coverage..."
	@. .venv/bin/activate && pytest --cov=teleclaude --cov-report=term-missing --cov-report=html --cov-report=xml --cov-report=json
	@echo ""
	@echo "✓ Coverage report generated"
	@echo "  - Terminal: see above"
	@echo "  - HTML: coverage/html/index.html"
	@echo "  - XML: coverage/coverage.xml"
	@echo "  - JSON: coverage/coverage.json"

coverage-html:
	@echo "Generating HTML coverage report..."
	@. .venv/bin/activate && pytest --cov=teleclaude --cov-report=html --cov-report=term-missing -q
	@echo "✓ HTML coverage report: coverage/html/index.html"

coverage-report: coverage-html
	@echo "Opening coverage report in browser..."
	@open coverage/html/index.html || xdg-open coverage/html/index.html || echo "Please open coverage/html/index.html manually"

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
