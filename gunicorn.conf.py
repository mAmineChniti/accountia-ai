"""
Gunicorn configuration for Accountia AI Accountant.
Optimized for Render deployment with Uvicorn workers.
"""

import multiprocessing
import os

# -----------------------------------------------------------------------------
# Server Socket
# -----------------------------------------------------------------------------
# Bind is set via --bind in start.sh (uses PORT env var)
# bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
backlog = 2048  # Number of pending connections allowed

# -----------------------------------------------------------------------------
# Worker Processes
# -----------------------------------------------------------------------------
# Workers: Use WEB_CONCURRENCY env var (set by Render), default to 1 for free tier
# Free tier has 512MB RAM - can only fit 1 worker
workers = int(os.getenv("WEB_CONCURRENCY", os.getenv("GUNICORN_WORKERS", "1")))

# Use Uvicorn workers for async support
worker_class = "uvicorn.workers.UvicornWorker"

# Worker timeout - increased for model inference
# Render has 100-second request timeout anyway
timeout = 120

# Graceful timeout for completing requests during shutdown
graceful_timeout = 30

# Keep-alive connections
keepalive = 5

# Max requests per worker before restart (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50  # Randomize to prevent all workers restarting at once

# Preload app is DISABLED because each worker needs its own model instance
# Model loading happens in worker process to ensure proper isolation
preload_app = False

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
# Use JSON/structured logging via structlog
capture_output = True
enable_stdio_inheritance = True

# Log level
loglevel = os.getenv("LOG_LEVEL", "info")

# Access log format (Render expects stdout logging)
accesslog = "-"  # stdout
errorlog = "-"   # stderr

# Access log format
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# -----------------------------------------------------------------------------
# Process Naming
# -----------------------------------------------------------------------------
proc_name = "accountia-ai"

# -----------------------------------------------------------------------------
# Server Mechanics
# -----------------------------------------------------------------------------
# Daemon mode (False for containerized environments)
daemon = False

# PID file (not needed in containers)
pidfile = None

# -----------------------------------------------------------------------------
# SSL (handled by Render's load balancer, not the app)
# -----------------------------------------------------------------------------
# keyfile = None
# certfile = None

# -----------------------------------------------------------------------------
# Worker Lifecycle Hooks
# -----------------------------------------------------------------------------
def on_starting(server):
    """Called just before the master process is initialized."""
    print(f"[GUNICORN] Starting Accountia AI with {workers} workers")


def on_reload(server):
    """Called when receiving SIGHUP signal."""
    print("[GUNICORN] Configuration reload requested")


def when_ready(server):
    """Called just after the server is started."""
    print(f"[GUNICORN] Server ready, listening on {bind}")


def worker_int(worker):
    """Called when a worker receives SIGINT or SIGQUIT."""
    print(f"[GUNICORN] Worker {worker.pid} interrupted")


def worker_abort(worker):
    """Called when a worker receives SIGABRT."""
    print(f"[GUNICORN] Worker {worker.pid} aborted")


def on_exit(server):
    """Called just before exiting Gunicorn."""
    print("[GUNICORN] Server shutting down")


# -----------------------------------------------------------------------------
# Worker-Specific Configuration
# -----------------------------------------------------------------------------
# Uvicorn worker settings are passed via worker_class options
# These are applied when using uvicorn.workers.UvicornWorker

# Equivalent uvicorn settings:
# --loop uvloop (if available, else asyncio)
# --http h11
# --ws websockets
# --lifespan on
# --interface asgi3

# Environment-specific tuning
if os.getenv("RENDER") == "true":
    # Render-specific optimizations
    print("[GUNICORN] Running on Render - applying Render-specific settings")
    # Keep workers lower on Render to avoid memory issues
    workers = min(workers, 2)
