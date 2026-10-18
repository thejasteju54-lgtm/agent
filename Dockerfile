# ============================================================================
# MarketPulse AI — Cloud Container Runtime
# Multi-stage production Dockerfile
# ============================================================================

# Stage 1: Build & dependency wheels
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip build wheel
# Install application and cloud dependencies into a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy source tree and build package
COPY src ./src
COPY README.md ./
RUN pip install --no-cache-dir . psycopg2-binary>=2.9.0

# Stage 2: Runtime image
FROM python:3.11-slim AS runner

WORKDIR /app

# Install minimal runtime dependencies (libpq for postgres)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV OPERATING_MODE=cloud
ENV ENVIRONMENT=production

# Create non-root user and runtime directories
RUN useradd -m -u 1001 marketpulse && \
    mkdir -p /app/data /app/artifacts /app/logs && \
    chown -R marketpulse:marketpulse /app

COPY --chown=marketpulse:marketpulse src ./src
COPY --chown=marketpulse:marketpulse pyproject.toml ./

USER marketpulse

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

ENTRYPOINT ["uvicorn", "marketpulse.api.app:app", "--host", "0.0.0.0", "--port", "8001"]
