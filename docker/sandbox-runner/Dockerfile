FROM python:3.12-slim

WORKDIR /app

# Copy only teleclaude.events (no daemon code) and the minimal pyproject for the image
COPY docker/sandbox-runner/pyproject.toml /app/pyproject.toml
COPY teleclaude/events/ /app/teleclaude/events/

# Install teleclaude.events and its minimal dependencies only
RUN pip install --no-cache-dir -e /app

# Verify no teleclaude daemon code is present (build-time gate)
RUN python -c "import teleclaude.core" 2>/dev/null && echo "ERROR: teleclaude daemon found in sandbox runner image" && exit 1 || echo "OK: no teleclaude daemon in image"

ENTRYPOINT ["python", "-m", "teleclaude.events.sandbox"]
