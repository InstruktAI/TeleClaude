#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s {run|html|report}\n' "$0" >&2
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

run_coverage() {
    echo "Running tests with coverage..."
    uv run pytest --cov=teleclaude --cov-report=term-missing --cov-report=html --cov-report=xml --cov-report=json
    echo ""
    echo "✓ Coverage report generated"
    echo "  - Terminal: see above"
    echo "  - HTML: coverage/html/index.html"
    echo "  - XML: coverage/coverage.xml"
    echo "  - JSON: coverage/coverage.json"
}

run_coverage_html() {
    echo "Generating HTML coverage report..."
    uv run pytest --cov=teleclaude --cov-report=html --cov-report=term-missing -q
    echo "✓ HTML coverage report: coverage/html/index.html"
}

run_coverage_report() {
    run_coverage_html
    echo "Opening coverage report in browser..."
    # the browser-open differs by platform/headless env; the final echo prints the
    # report path so a failed open never loses the artifact location
    open coverage/html/index.html || xdg-open coverage/html/index.html || echo "Please open coverage/html/index.html manually"
}

if [ "$#" -ne 1 ]; then
    usage
    exit 2
fi

case "$1" in
    run) run_coverage ;;
    html) run_coverage_html ;;
    report) run_coverage_report ;;
    *)
        usage
        exit 2
        ;;
esac
