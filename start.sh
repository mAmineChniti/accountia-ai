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

# Set HuggingFace cache to use the pre-downloaded model
echo "[STARTUP] Setting up model cache..."
export HF_HOME="/app/.cache/huggingface"
export TRANSFORMERS_CACHE="/app/.cache/huggingface"
export HF_HUB_OFFLINE=1  # Don't try to re-download if model exists

# Verify model cache exists
if [ -d "/app/.cache/huggingface/models--Qwen--Qwen2.5-1.5B-Instruct" ]; then
    echo "[STARTUP] Model cache found (build-time download successful)"
    ls -la /app/.cache/huggingface/models--Qwen--Qwen2.5-1.5B-Instruct/ | head -20
else
    echo "[WARN] Model cache not found - will attempt download at runtime"
    unset HF_HUB_OFFLINE
fi

# Memory optimization for Render's constrained environments
echo "[STARTUP] Setting memory optimizations..."
export MALLOC_ARENA_MAX=2
export PYTHONOPTIMIZE=2

# Gunicorn worker calculation (can be overridden via GUNICORN_WORKERS)
if [ -n "$GUNICORN_WORKERS" ]; then
    WORKERS="$GUNICORN_WORKERS"
else
    # Auto-calculate based on Render instance
    # Render instances typically have 1-4 cores
    # Use 2 workers to balance throughput and memory (model is ~2-3GB per worker)
    WORKERS=2
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
    --enable-stdio-inheritance \
    --preload  # Preload app for memory efficiency (disabled in gunicorn.conf.py for model isolation)
