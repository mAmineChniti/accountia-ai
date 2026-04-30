#!/bin/bash
# ============================================================================
# Production startup script for Accountia AI Accountant
# Handles Gunicorn startup with proper signal handling for Render
# ============================================================================

set -e

echo "=========================================="
echo "Accountia AI Accountant - Starting up"
echo "=========================================="

# Verify required environment variables
echo "[STARTUP] Verifying environment..."

if [ -z "$MONGO_URI" ]; then
    echo "[ERROR] MONGO_URI environment variable is required"
    exit 1
fi

if [ -z "$API_KEY" ]; then
    echo "[WARN] API_KEY not set - service will run without authentication"
fi

# Log configuration
echo "[STARTUP] Configuration:"
echo "  - PORT: ${PORT:-8000}"
echo "  - WORKERS: ${GUNICORN_WORKERS:-auto}"
echo "  - LOG_LEVEL: ${LOG_LEVEL:-info}"
echo "  - REDIS_URL: ${REDIS_URL:-not configured}"

echo "[STARTUP] Using built-in TensorFlow analyzer (no HuggingFace models required)"

# Memory optimization for Render's constrained environments
echo "[STARTUP] Setting memory optimizations..."
export MALLOC_ARENA_MAX=2
# Use optimize level 1 - level 2 strips docstrings needed by transformers
export PYTHONOPTIMIZE=1

# Gunicorn worker calculation (can be overridden via GUNICORN_WORKERS)
if [ -n "$GUNICORN_WORKERS" ]; then
    WORKERS="$GUNICORN_WORKERS"
else
    # Auto-calculate based on Render instance
    # Free tier (512MB): Use 1 worker only - 0.5B model + overhead fits in memory
    # Paid tiers (2GB+): Can use 2 workers with larger models
    WORKERS=1
fi

echo "[STARTUP] Starting Gunicorn with $WORKERS workers..."

# Start Gunicorn with Uvicorn workers
# exec replaces the shell process so signals are properly handled
exec gunicorn \
    "app.main:app" \
    --config gunicorn.conf.py \
    --workers "$WORKERS" \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind "0.0.0.0:${PORT:-8000}" \
    --timeout 120 \
    --graceful-timeout 30 \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    --access-logfile - \
    --error-logfile - \
    --log-level "${LOG_LEVEL:-info}" \
    --capture-output \
    --enable-stdio-inheritance
