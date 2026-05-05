# Deployment Guide - Accountia AI Accountant

Production-ready deployment guide for Render (and other Docker-based platforms).

## Quick Start

### 1. Deploy to Render (Recommended)

```bash
# 1. Push code to GitHub
git add .
git commit -m "Production-ready deployment"
git push origin main

# 2. In Render Dashboard:
# - Click "New +" → "Blueprint"
# - Connect your GitHub repo
# - Render will read render.yaml and create the service

# 3. Set required environment variables in Render Dashboard:
# - MONGO_URI: Your MongoDB Atlas connection string
# - API_KEY: Generate with: openssl rand -hex 32
# - REDIS_URL: (optional) Your Redis connection string
# - GROQ_API_KEY: (optional) For LLM fallback
```

### 2. Manual Docker Build (Testing)

```bash
# Build the image locally
docker build -t accountia-ai .

# Run locally (for testing)
docker run -p 8000:8000 \
  -e MONGO_URI="mongodb://..." \
  -e API_KEY="test-key" \
  -e REDIS_URL="redis://..." \
  accountia-ai
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Render Load Balancer                                       │
│  (HTTPS termination, health checks)                         │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Gunicorn Master Process                                      │
│  ├── Worker 1 (Model + FastAPI)                              │
│  └── Worker 2 (Model + FastAPI)                              │
│                                                              │
│  Each worker has:                                            │
│  - Own model instance (~2-3GB RAM each)                      │
│  - Isolated memory space (no shared state)                   │
│  - Async request handling                                    │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ MongoDB Atlas│   │ Redis Cache  │   │ Groq API     │
│ (State)      │   │ (Optional)   │   │ (Fallback)   │
└──────────────┘   └──────────────┘   └──────────────┘
```

## Environment Variables

### Required

| Variable    | Description                                                       | Example                                                          |
| ----------- | ----------------------------------------------------------------- | ---------------------------------------------------------------- |
| `MONGO_URI` | MongoDB Atlas connection string                                   | `mongodb+srv://user:pass@cluster.mongodb.net/accountia_platform` |
| `API_KEY`   | API key for authentication (generate with `openssl rand -hex 32`) | `abc123...`                                                      |

### Optional

| Variable           | Default    | Description                                                                                                                                    |
| ------------------ | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `REDIS_URL`        | -          | Redis connection for caching/rate limiting                                                                                                     |
| `GROQ_API_KEY`     | -          | Groq API key for LLM fallback                                                                                                                  |
| `GUNICORN_WORKERS` | `2`        | Number of worker processes (each loads a model)                                                                                                |
| `LOG_LEVEL`        | `info`     | Logging level (debug, info, warning, error)                                                                                                    |
| `DEVICE`           | `cpu`      | Compute device (cpu/cuda - Render uses CPU)                                                                                                    |
| `BASE_MODEL`       | (optional) | Base model id or local path. Leave empty to use built-in TensorFlow analyzer or provide an external model when optional ML deps are installed. |
| `USE_FINE_TUNED`   | `false`    | Whether to use fine-tuned LoRA adapter                                                                                                         |

### Render-Specific

| Variable  | Value                     | Description                                                                  |
| --------- | ------------------------- | ---------------------------------------------------------------------------- |
| `RENDER`  | `true`                    | Marks Render environment for special handling                                |
| `HF_HOME` | `/app/.cache/huggingface` | (legacy) HuggingFace cache location — optional when using external HF models |

## Performance Tuning

### Memory Considerations

- **Model Size**: Qwen 1.5B is ~3GB in CPU mode
- **Per-Worker Memory**: ~4GB per worker (model + overhead)
- **Recommended Render Plan**: Standard ($7/month) minimum for 2 workers

### Worker Count

Set based on your Render instance size:

```bash
# Starter plan (512MB RAM) - 1 worker only
GUNICORN_WORKERS=1

# Standard plan (2GB RAM) - 1-2 workers
GUNICORN_WORKERS=2

# Pro plans - scale accordingly (2-4 workers)
GUNICORN_WORKERS=4
```

Each worker:

- Handles requests independently
- Loads its own model copy (no sharing)
- Can be restarted without affecting others

### Cold Start Optimization

The default setup uses the lightweight in-repo TensorFlow analyzer which
does not require large external model downloads and starts quickly. If you
opt to use an external large model via `BASE_MODEL`, consider pre-downloading
the model during image build in CI to improve cold starts. Pre-baking is
optional and only necessary for heavy models when you control the runtime
environment and disk budget.

## Health Checks

Render uses these endpoints:

- **Liveness**: `GET /api/health` - Returns 200 if service is running
- **Readiness**: `GET /api/health/ready` - Returns 200 only when MongoDB + Model are ready
- **Detailed Status**: `GET /api/health/status` - Full diagnostic info

## Scaling Strategy

### Horizontal Scaling (Recommended)

```yaml
# render.yaml
numInstances: 2 # Add more instances as needed
```

Each instance:

- Is independent with its own workers
- Has its own model copies
- Connects to same MongoDB/Redis

### Vertical Scaling

Increase Render plan for more workers per instance:

- More RAM = more workers = higher throughput
- But: diminishing returns due to CPU contention

## Security Checklist

- [ ] Set strong `API_KEY` (32+ hex chars)
- [ ] Use MongoDB Atlas with IP allowlist (Render IP ranges)
- [ ] Enable Redis AUTH if using Redis
- [ ] Set `DEBUG=false` in production
- [ ] Enable Render's "Auto-deploy" with branch protection
- [ ] Review CORS settings (currently `[]` in production)

## Monitoring & Debugging

### Logs

View structured logs in Render Dashboard:

```
[STARTUP] Starting Accountia AI Accountant...
[STARTUP] Worker PID: 42
[model_initialization_started] model=Qwen/Qwen2.5-1.5B-Instruct worker_pid=42
[model_initialization_completed] worker_pid=42 device=cpu
[service_started_successfully] worker_pid=42 model_ready=True
```

### Common Issues

| Issue                 | Cause                  | Solution                                      |
| --------------------- | ---------------------- | --------------------------------------------- |
| Readiness probe fails | Model not loading      | Check logs for model errors; verify `HF_HOME` |
| High memory usage     | Too many workers       | Reduce `GUNICORN_WORKERS`                     |
| Slow cold starts      | Runtime model download | Ensure `HF_HUB_OFFLINE=1` and model in image  |
| 429 errors            | Rate limiting          | Check Redis connection or increase limits     |
| MongoDB timeouts      | Atlas IP not allowed   | Add Render IP ranges to Atlas allowlist       |

## Load Testing

```bash
# Install k6: https://k6.io/

# Test health endpoint
k6 run --vus 10 --duration 30s - <<EOF
import http from 'k6/http';
export default function() {
  http.get('https://your-service.onrender.com/api/health');
}
EOF

# Test accounting job creation (with auth)
k6 run --vus 5 --duration 60s - <<EOF
import http from 'k6/http';
export default function() {
  http.post('https://your-service.onrender.com/api/accounting/jobs',
    JSON.stringify({
      businessId: 'test',
      periodStart: '2024-01-01',
      periodEnd: '2024-01-31'
    }),
    { headers: { 'X-API-Key': 'your-api-key', 'Content-Type': 'application/json' } }
  );
}
EOF
```

## Cost Optimization

For Render:

| Strategy                 | Impact                                          |
| ------------------------ | ----------------------------------------------- |
| Use pre-downloaded model | Faster cold starts, no bandwidth costs          |
| Redis caching            | Reduces redundant LLM calls                     |
| Request deduplication    | Prevents duplicate processing                   |
| Rate limiting            | Prevents abuse, reduces costs                   |
| Groq fallback            | Cheaper than larger instances for high LLM load |

## Rollback Strategy

1. Tag releases: `git tag -a v1.0.0 -m "Production release"`
2. If issues arise, redeploy previous tag in Render Dashboard
3. Render keeps previous deployments for quick rollback

## Support

For deployment issues:

1. Check Render Dashboard logs
2. Verify environment variables
3. Test health endpoints: `curl https://your-service.onrender.com/api/health/status`
4. Review this guide's "Common Issues" section
