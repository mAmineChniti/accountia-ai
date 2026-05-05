# ============================================================================
# Production Dockerfile for Accountia AI Accountant
# Python 3.11, Render-optimized, with build-time model caching
# ============================================================================

# ----------------------------------------------------------------------------
# Stage 1: Base image with system dependencies
# ----------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Reduce memory fragmentation
    MALLOC_ARENA_MAX=2 \
    # Python optimizations
    PYTHONOPTIMIZE=1

# Reduce TensorFlow verbosity and limit OpenMP threads in container
ENV TF_CPP_MIN_LOG_LEVEL=2 \
    OMP_NUM_THREADS=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libgomp1 \
    # Linear algebra libs used by numpy/TensorFlow wheels
    libopenblas-dev \
    liblapack3 \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/false appuser

# ----------------------------------------------------------------------------
# Stage 2: Dependencies installation
# ----------------------------------------------------------------------------
FROM base AS deps

WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .

# Install Python dependencies
# Use --no-deps for specific packages if needed, but install full requirements
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# ----------------------------------------------------------------------------
# Final production image
# ----------------------------------------------------------------------------
FROM base AS production

WORKDIR /app

# Copy installed Python packages from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy downloaded model from model-downloader stage

# Copy application code
COPY --chown=appuser:appgroup app/ ./app/

# Copy gunicorn config
COPY --chown=appuser:appgroup gunicorn.conf.py .

# Copy startup script
COPY --chown=appuser:appgroup start.sh .
RUN chmod +x start.sh

# Ensure cache and analyzer_model directories have correct permissions
RUN mkdir -p /app/.cache /app/analyzer_model && \
    chown -R appuser:appgroup /app/.cache /app/analyzer_model && \
    chmod -R 755 /app/.cache /app/analyzer_model

# Switch to non-root user
USER appuser

# Expose port (Render sets PORT env var)
EXPOSE ${PORT:-8000}

# Health check (Render uses this)
# Use PORT env var (set by Render), fallback to 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f "http://localhost:${PORT:-8000}/api/health" || exit 1

# Production command
CMD ["./start.sh"]
