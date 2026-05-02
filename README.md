# Accountia - AI Accountant Service

AI-powered accounting service that processes invoices, generates double-entry journal entries, calculates Tunisian taxes, and produces financial reports.

This README documents the current codebase and public HTTP API implemented in this repository. It has been updated to match the current routes and behavior in `app/`.

## Quick overview

- Web framework: FastAPI
- Persistence: MongoDB (platform DB + per-tenant DBs)
- Cache / auxiliary: Redis (caching, deduplication, rate limiting)
- LLM: Groq API (optional) for structured generation; local LLM support removed in this build
- Built-in analyzer: `TinyAccountingAnalyzer` (TensorFlow/Keras based) with rule-based fallback

## What the service implements now

Only the endpoints and functionality below are currently implemented and mounted by default in `app/main.py`.

### Public endpoints

Base URL: `http://<host>:8000`

- GET `/` — Service info (service name, version, status). No auth required.
- GET `/api/health` — Combined liveness/readiness. Reports checks for MongoDB, Redis (optional) and model readiness. Returns HTTP 200 when critical components are ready (MongoDB + model readiness in this build); otherwise returns HTTP 503 with a `not_ready` status.

Accounting API (mounted at `/api/accounting`):

- POST `/api/accounting/jobs`
  - Create an accounting job for a business period.
  - Body: `{ businessId, periodStart, periodEnd }` (camelCase)
  - Validations: period_end >= period_start; period length <= 365 days.
  - Behavior: resolves tenant DB via `BusinessService`, creates a platform-side `AccountingTask` (Beanie) and upserts a tenant-side copy, then schedules background processing.
  - Returns task metadata and ETA.

- GET `/api/accounting/jobs?businessId={businessId}&limit={n}`
  - List recent accounting jobs for a business (tenant DB `accounting_tasks` read).
  - Query params: `businessId` (required), `limit` (1-100, default 10).

- GET `/api/accounting/jobs/{task_id}?businessId={businessId}`
  - Get job status; if the job is completed returns the full results (financial summary, tax breakdowns, journal entries preview, AI insights). While processing returns a lightweight status object.

- GET `/api/accounting/jobs/{task_id}/results?businessId={businessId}`
  - Return the full `AccountingResultsResponse` for a completed job. Returns 400 if job not completed, 404 if task not found.

Tax endpoints (persisted results):

- POST `/api/accounting/taxes/{business_id}/{year}`
  - Calculate taxes for the specified year for the tenant, produce an analysis via the tiny analyzer, and upsert a `tax_results` document in the tenant DB. Returns a location pointer to the GET endpoint.

- GET `/api/accounting/taxes/{business_id}/{year}`
  - Retrieve the previously persisted tax result. Returns 404 if not found.

### Removed / Not mounted

- There is no mounted training/admin router by default. Any documentation describing training endpoints or an administrative training router was removed because it is not mounted and not part of the default service surface.
- Endpoints for cancelling jobs or fine-grained admin history endpoints are not present in the current code.

## Security

- The project includes helpers in `app/core/security.py`:
  - `verify_api_key` — checks `X-API-Key` header against `API_KEY` (if configured)
  - `verify_optional_jwt` — accepts a Bearer token (no validation by default)
  - `secure_endpoint` — combined dependency that returns auth context

- Current behavior: Routes are protected only if the code applies the dependency. The repository supports API-key enforcement, but it is opt-in per-route. To enable enforcement globally for accounting routes, add `Depends(secure_endpoint)` to the route definitions or apply the dependency on the router.

- To enforce API key: set `API_KEY` in the environment (or `.env`) and apply `secure_endpoint` to routes. If `API_KEY` is not set the service will run without enforced route-level protection and will log a warning.

## Operational notes

- MongoDB
  - `app/db/mongodb.py` exposes `init_mongodb()`, `get_platform_db()` and `get_tenant_db(database_name)`.
  - Platform documents (Beanie models) are initialised during startup.

- Redis
  - `app/db/redis.py` provides `cache_get`, `cache_set`, `dedup_check`, and `rate_limit_check` and is used for caching analyzer outputs, deduping long-running requests, and rate limiting.

- Rate limiting
  - Middleware `RateLimiter` is registered in `app/main.py`. It uses Redis and is configured to fail-open if Redis is unavailable (requests allowed), and adds rate-limit headers to responses.

- Analyzer
  - `TinyAccountingAnalyzer` uses `TFAccountingAnalyzer` when a TensorFlow model exists in `/app/.cache/tf_analyzer`. If TF is unavailable or model files are missing it falls back to rule-based analysis. Health currently reports model readiness as a modeled check.

- LLM
  - Local LLM support has been removed. `app/services/llm_service.py` supports the Groq API when `GROQ_API_KEY` is configured. If not configured structured LLM generation will not be available and engine falls back to internal rule-based logic.

## Data model (high level)

- `AccountingTask` (tenant `accounting_tasks` collection) — task_id, business_id, period_start/end, status, journal_entries, tax_calculations, financial_summary, reports, ai_insights, recommendations, anomalies_detected, created_at, processed_by.
- `tax_results` (tenant collection) — persisted annual tax results with analysis and timestamps.

See `app/db/schemas.py` for full Pydantic/Beanie model definitions.

## How to run locally

1. Create a Python venv and install requirements:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

2. Set `.env` (or environment variables) for `MONGO_URI` (required). Optional but recommended: `API_KEY`, `GROQ_API_KEY`, `REDIS_URL`.

3. Start the service for development:

```bash
uvicorn app.main:app --reload
```

4. Example calls (replace values):

```bash
# Health
curl -i http://127.0.0.1:8000/api/health

# Create job
curl -i -X POST http://127.0.0.1:8000/api/accounting/jobs \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your_key>" \
  -d '{"businessId":"<id>","periodStart":"2024-01-01T00:00:00Z","periodEnd":"2024-01-31T23:59:59Z"}'

# List jobs
curl -i "http://127.0.0.1:8000/api/accounting/jobs?businessId=<id>&limit=10" -H "X-API-Key: <your_key>"

# Get job status
curl -i "http://127.0.0.1:8000/api/accounting/jobs/<task_id>?businessId=<id>" -H "X-API-Key: <your_key>"

# Calculate taxes for a year (will persist)
curl -i -X POST "http://127.0.0.1:8000/api/accounting/taxes/<id>/2024" -H "X-API-Key: <your_key>"

# Get persisted tax results
curl -i "http://127.0.0.1:8000/api/accounting/taxes/<id>/2024" -H "X-API-Key: <your_key>"
```

### Endpoint details

Below are exact request and response shapes for each public endpoint. Authentication notes: the service supports `X-API-Key` enforcement via `secure_endpoint`, but routes are only protected if the dependency is applied. Examples below show the header where relevant.

- **GET /**
  - Description: Service info.
  - Auth: none
  - Request: none
  - Responses:
    - 200 OK
      ```json
      {
        "service": "accountia",
        "version": "0.1.0",
        "status": "ok"
      }
      ```

- **GET /api/health**
  - Description: Liveness + readiness. Checks MongoDB and model readiness (model check is considered critical in this build).
  - Auth: none
  - Request: none
  - Responses:
    - 200 OK
      ```json
      {
        "status": "ready",
        "checks": {
          "mongodb": true,
          "redis": true,
          "model": true
        },
        "workerPid": 12345,
        "modelInfo": {
          "name": "tiny_tensorflow_analyzer",
          "ready": true,
          "using_tensorflow": true,
          "model_path": true
        },
        "service": "accountia",
        "version": "0.1.0",
        "timestamp": "2024-05-01T12:00:00+00:00"
      }
      ```
    - 503 Service Unavailable
      ```json
      {
        "status": "not_ready",
        "checks": {
          "mongodb": true,
          "redis": false,
          "model": false
        },
        "workerPid": 12345,
        "modelInfo": {
          "name": "tiny_tensorflow_analyzer",
          "ready": false,
          "using_tensorflow": true,
          "model_path": false
        },
        "service": "accountia",
        "version": "0.1.0",
        "timestamp": "2024-05-01T12:00:00+00:00"
      }
      ```

- **POST /api/accounting/jobs**
  - Description: Create an accounting job for a business period.
  - Auth: optional (see security notes). Example uses `X-API-Key` header.
  - Request (application/json):
    ```json
    {
      "businessId": "string",        // required
      "periodStart": "2024-01-01T00:00:00Z", // ISO8601 string, required
      "periodEnd": "2024-01-31T23:59:59Z"    // ISO8601 string, required
    }
    ```
  - Responses:
    - 201 Created
      ```json
      {
        "taskId": "645f1b2c9a1e4f3b2c9a9999",
        "businessId": "biz_001",
        "status": "pending",
        "message": "Accounting job created for period 2024-01-01 to 2024-01-31",
        "estimatedSeconds": 45,
        "estimatedCompletion": "2024-02-01T12:35:41Z"
      }
      ```
    - 400 Bad Request (validation)
      ```json
      { "detail": "periodEnd must be after periodStart" }
      ```

- **GET /api/accounting/jobs?businessId={businessId}&limit={n}**
  - Description: List recent jobs for a business.
  - Auth: optional
  - Query params:
    - `businessId` (string, required)
    - `limit` (integer, optional, 1-100, default 10)
  - Responses:
    - 200 OK
      ```json
      {
        "businessId": "biz_001",
        "jobs": [
          {
            "taskId": "645f1b2c9a1e4f3b2c9a1234",
            "periodStart": "2024-01-01T00:00:00Z",
            "periodEnd": "2024-01-31T23:59:59Z",
            "status": "completed",
            "progressPercent": 100,
            "estimatedSeconds": 45,
            "estimatedCompletion": "2024-02-01T12:35:41Z",
            "estimatedTimeRemaining": 0,
            "startedAt": "2024-01-31T12:00:00Z",
            "completedAt": "2024-02-01T12:34:56Z",
            "journalEntriesCount": 42,
            "reportsGenerated": 3
          },
          {
            "taskId": "645f1b2c9a1e4f3b2c9a5678",
            "periodStart": "2024-02-01T00:00:00Z",
            "periodEnd": "2024-02-28T23:59:59Z",
            "status": "processing",
            "progressPercent": 42,
            "estimatedSeconds": 90,
            "estimatedCompletion": "2024-03-01T08:16:30Z",
            "estimatedTimeRemaining": 52,
            "startedAt": "2024-03-01T08:15:00Z",
            "completedAt": null,
            "journalEntriesCount": 12,
            "reportsGenerated": 0
          }
        ]
      }
      ```

- **GET /api/accounting/jobs/{task_id}?businessId={businessId}**
  - Description: Get job status and (if completed) results summary.
  - Auth: optional
  - Path params: `task_id` (string)
  - Query params: `businessId` (string, required)
  - Responses:
    - 200 OK (processing)
      ```json
      {
        "taskId": "645f1b2c9a1e4f3b2c9a5678",
        "businessId": "biz_001",
        "periodStart": "2024-02-01T00:00:00Z",
        "periodEnd": "2024-02-28T23:59:59Z",
        "status": "processing",
        "progressPercent": 42,
        "startedAt": "2024-03-01T08:16:00Z",
        "completedAt": null,
        "errorMessage": null,
        "journalEntriesCount": 12,
        "reportsGenerated": 0,
        "estimatedSeconds": 90,
        "estimatedCompletion": "2024-03-01T08:16:30Z",
        "estimatedTimeRemaining": 52
      }
      ```
    - 200 OK (completed)
      Returns the full results payload (same schema as GET `/api/accounting/jobs/{task_id}/results`). See the detailed `AccountingResultsResponse` example in the `GET /api/accounting/jobs/{task_id}/results` section below.
    - 404 Not Found
      ```json
      { "detail": "task not found" }
      ```

- **GET /api/accounting/jobs/{task_id}/results?businessId={businessId}**
  - Description: Full results payload for a completed job.
  - Auth: optional
  - Responses:
    - 200 OK
      ```json
      {
        "taskId": "645f1b2c9a1e4f3b2c9a1234",
        "businessId": "biz_001",
        "periodStart": "2024-01-01T00:00:00Z",
        "periodEnd": "2024-01-31T23:59:59Z",
        "status": "completed",
        "totalRevenue": 12345.67,
        "totalExpenses": 10999.00,
        "grossProfit": 6913.57,
        "netProfit": 2345.67,
        "accountsReceivable": 2000.00,
        "accountsPayable": 1200.00,
        "cashPosition": 5000.00,
        "taxCalculations": [
          {
            "taxType": "VAT",
            "jurisdiction": "TN",
            "taxableAmount": 1000.0,
            "taxRate": 0.19,
            "taxAmount": 190.0,
            "notes": "Standard VAT"
          }
        ],
        "aiInsights": "Anomaly: missing invoices for 2024-01-15",
        "recommendations": ["Review vendor X"],
        "anomaliesDetected": [{"type":"missing_invoice","detail":"INV-2024-015","severity":"medium"}],
        "reports": [
          {"reportType": "P&L", "periodStart": "2024-01-01T00:00:00Z", "periodEnd": "2024-01-31T23:59:59Z", "data": {}}
        ],
        "journalEntries": [
          {"date": "2024-01-05", "account": "Accounts Receivable", "debit": 1000.0, "credit": 0.0, "description": "Invoice INV-1001", "invoiceId": "INV-1001"}
        ],
        "totalJournalEntries": 42
      }
      ```
    - 400 Bad Request (not completed)
      ```json
      { "detail": "task not completed" }
      ```

- **POST /api/accounting/taxes/{business_id}/{year}**
  - Description: Compute and persist annual tax result for a business.
  - Auth: optional
  - Path params: `business_id` (string), `year` (int)
  - Request: none (service reads tenant data)
  - Responses:
    - 201 Created
      ```json
      { "businessId": "biz_001", "year": 2024, "success": true }
      ```
    - 404 Not Found (tenant or data missing)
      ```json
      { "detail": "business not found or no accounting data for year" }
      ```

- **GET /api/accounting/taxes/{business_id}/{year}**
  - Description: Retrieve persisted tax result for a business/year.
  - Auth: optional
  - Responses:
    - 200 OK
      ```json
      {
        "businessId": "biz_001",
        "year": 2024,
        "taxBreakdown": {
          "vat_standard_19": 190.0,
          "vat_reduced_13": 0.0,
          "vat_reduced_7": 0.0,
          "vat_exempt": 0.0,
          "vat_total": 190.0,
          "taxable_income": 10000.0,
          "corporate_tax_rate": 0.15,
          "corporate_tax_due": 1500.0,
          "withholding_tax": 15.0,
          "total_tax_liability": 1705.0,
          "filing_period": "01/2024",
          "due_date": "2024-02-28T00:00:00Z"
        },
        "analysis": {
          "insights": "Basic analysis summary",
          "recommendations": ["Confirm VAT filings for Q2"],
          "anomalies": [
            { "type": "missing_invoice", "detail": "Invoice INV-2024-015 missing line items", "severity": "medium" }
          ]
        },
        "createdAt": "2024-04-01T10:00:00Z",
        "lastUpdatedAt": "2024-04-01T10:00:00Z"
      }
      ```
    - 404 Not Found
      ```json
      { "detail": "tax result not found" }
      ```

## Development & quality

- Tests: `pytest` (tests in `tests/`)
- Lint: `ruff` configured via `Makefile`/`pyproject.toml`

## Notes & recommended cleanup

- Remove or mount training/admin routers only when you intentionally enable training flows.
- Consider making the model check non-critical in `/api/health` if you want readiness to be `200` when the rule-based analyzer is used.
- Protect sensitive endpoints by applying `secure_endpoint` dependency or adding middleware that enforces API-key globally.

If you want, I can now:
- apply `secure_endpoint` to all accounting routes so they require the API key, or
- remove the model from the health critical checks so readiness is tolerant when TF model is absent, or
- generate a compact OpenAPI summary file / docs update for consumers.

Tell me which change you'd like next and I'll implement it.
