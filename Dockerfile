# ============================================================================
# Production Dockerfile for Accountia AI Accountant
# Python 3.14, Render-optimized, with build-time model caching
# ============================================================================

# ----------------------------------------------------------------------------
# Stage 1: Base image with system dependencies
# ----------------------------------------------------------------------------
FROM python:3.14-slim-bookworm AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # HF cache location - will be baked into the image
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/app/.cache/huggingface \
    HF_DATASETS_CACHE=/app/.cache/huggingface/datasets \
    # Disable telemetry
    HF_HUB_DISABLE_TELEMETRY=1 \
    # Reduce memory fragmentation
    MALLOC_ARENA_MAX=2 \
    # Python optimizations
    PYTHONOPTIMIZE=2

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libgomp1 \
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
RUN pip install --no-cache-dir -r requirements.txt

# ----------------------------------------------------------------------------
# Stage 3: Model download (critical for Render cold starts)
# ----------------------------------------------------------------------------
FROM deps AS model-downloader

WORKDIR /app

# Install huggingface_hub for model download
RUN pip install --no-cache-dir huggingface-hub

# Copy and run model download script
COPY download_model.py /tmp/download_model.py
RUN python3 /tmp/download_model.py && chmod -R 755 /app/.cache/huggingface && rm /tmp/download_model.py

# ----------------------------------------------------------------------------
# Stage 4: Final production image
# ----------------------------------------------------------------------------
FROM base AS production

WORKDIR /app

# Copy installed Python packages from deps stage
COPY --from=deps /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy downloaded model from model-downloader stage
COPY --from=model-downloader /app/.cache/huggingface /app/.cache/huggingface

# Copy application code
COPY --chown=appuser:appgroup app/ ./app/

# Copy gunicorn config
COPY --chown=appuser:appgroup gunicorn.conf.py .

# Copy startup script
COPY --chown=appuser:appgroup start.sh .
RUN chmod +x start.sh

# Ensure cache directories have correct permissions
RUN mkdir -p /app/.cache && \
    chown -R appuser:appgroup /app/.cache && \
    chmod -R 755 /app/.cache

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check (Render uses this)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health/ready || exit 1

# Production command
CMD ["./start.sh"]
