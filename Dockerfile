FROM python:3.12-slim

# Non-root runtime user
RUN useradd --system --create-home --uid 10001 appuser

WORKDIR /app

# Install deps first for layer caching
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

USER appuser

# The service reads /app/config.yaml by default; mount yours there, or supply
# everything via environment variables (see config.example.yaml / compose file).
ENV CONFIG_PATH=/app/config.yaml \
    PYTHONUNBUFFERED=1

# Healthcheck: the process must be alive AND connected. A minimal liveness probe
# here checks the module imports and config parses; refine once metrics exist.
HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import hass_airport_express" || exit 1

ENTRYPOINT ["python", "-m", "hass_airport_express"]
