FROM python:3.12-slim

WORKDIR /app

# Copy only teleclaude_events (no daemon code) and the minimal pyproject for the image
COPY docker/alpha-runner/pyproject.toml /app/pyproject.toml
COPY teleclaude_events/ /app/teleclaude_events/

# Install teleclaude_events and its minimal dependencies only
RUN pip install --no-cache-dir -e /app

# Verify no teleclaude daemon code is present (build-time gate)
RUN python -c "import teleclaude" 2>/dev/null && echo "ERROR: teleclaude daemon found in alpha runner image" && exit 1 || echo "OK: no teleclaude daemon in image"

ENTRYPOINT ["python", "-m", "teleclaude_events.alpha"]
