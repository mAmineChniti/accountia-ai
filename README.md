# Accountia - AI Accountant Service

A fine-tuned LLM-powered accounting service for the Accountia invoice platform. Replaces human accountants by automatically processing invoices, generating journal entries, calculating taxes, and producing financial reports.

## Features

- **Automated Accounting**: Process date-range accounting periods (e.g., Jan 1-31, 2024)
- **Journal Entry Generation**: Double-entry bookkeeping from invoice data (accrual basis)
- **Tunisian Tax Calculations**: VAT (19%, 13%, 7%), Corporate Tax (IS), Withholding Taxes
- **Financial Reports**: P&L, Balance Sheet, General Ledger
- **AI Insights**: LLM-powered analysis and recommendations
- **Anomaly Detection**: Automated red flag identification
- **Multi-tenancy**: Uses businessId to access tenant databases (like Accountia API)
- **AI Model**: Uses Qwen2.5-1.5B (works on 4GB GPU) - training optional for later
- **Security**: API key auth - only Accountia API can access (blocks direct frontend requests)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Accountia Service                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  FastAPI + Qwen2.5-1.5B-Instruct (or Groq API)    │   │
│  │  • Accounting Engine (accrual basis)              │   │
│  │  • Journal Entry Generator                        │   │
│  │  • Tunisian Tax Calculator (VAT, IS, Withholding) │   │
│  │  • Financial Report Generator                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                  │
│                          ▼                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  MongoDB (reads from Accountia tenant DBs)          │   │
│  │  Writes accounting results to accounting_tasks      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
															│
															│ HTTP API
															▼
┌─────────────────────────────────────────────────────────────┐
│                 Accountia NestJS API                        │
│     Businesses request accounting via this API               │
└─────────────────────────────────────────────────────────────┘
```

## API Documentation

**Base URL:** `http://localhost:8000`  
**Authentication:** `X-API-Key` header required for all `/api/accounting/*` routes

### Root Endpoint

`GET /`

Service info and basic health check. No authentication required.

**Response:**
```json
{
	"service": "Accountia AI Accountant",
	"version": "1.0.0",
	"status": "operational",
	"description": "AI-powered accounting for Tunisian businesses"
}
```

### Health Endpoints

#### Basic Health
`GET /api/health`

Quick health check - returns immediately.

**Response:**
```json
{
	"status": "healthy",
	"service": "Accountia AI Accountant"
}
```

#### Readiness Check
`GET /api/health/ready`

Deep health check - verifies MongoDB and AI model are ready.

**Response (Ready):**
```json
{
	"status": "ready",
	"checks": {
		"mongodb": true,
		"model": true
	}
}
```

**Response (Not Ready):**
```json
{
	"status": "not_ready",
	"checks": {
		"mongodb": false,
		"model": true
	}
}
```

### 1. Create Accounting Job

`POST /api/accounting/jobs`

Creates a new accounting job for a business period. The AI Accountant will:
1. Look up the business's database name from the platform DB
2. Read all invoices from that period
3. Generate journal entries and financial reports
4. Store results in the business's tenant database

**Request Body (use camelCase):**
```json
{
  "businessId": "60d5ecb8b6f3c72e7c8e4a5b",
  "periodStart": "2024-01-01T00:00:00Z",
  "periodEnd": "2024-01-31T23:59:59Z"
}
```

**Validation:** Period max 365 days, end must be after start.

**Response (New Job):**
```json
{
  "taskId": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
  "status": "pending",
  "message": "Accounting job created for period 2024-01-01 to 2024-01-31",
  "estimatedSeconds": 59,
  "estimatedCompletion": "2024-01-01T00:00:59Z"
}
```

**Response (Already Processing):**
```json
{
  "taskId": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
  "status": "processing",
  "message": "Accounting job already in progress."
}
```

**Response (Already Completed):**
```json
{
  "taskId": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
  "status": "completed",
  "message": "Accounting already completed. Use GET /jobs/{task_id} for results."
}
```

**Error Responses:**
- `400` - Invalid period (exceeds 365 days or end before start)
- `404` - Business not found
- `401/403` - Invalid or missing API key

### 2. List Accounting Jobs

`GET /api/accounting/jobs?businessId={businessId}&limit=10`

List all accounting jobs for a business.

**Query Parameters:**
- `businessId` (required) - Business ID
- `limit` (optional) - Max results (1-100, default 10)

**Response:**
```json
{
  "businessId": "60d5ecb8b6f3c72e7c8e4a5b",
  "jobs": [
    {
      "taskId": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
      "periodStart": "2024-01-01T00:00:00",
      "periodEnd": "2024-01-31T23:59:59",
      "status": "completed",
      "progressPercent": 100,
      "startedAt": "2024-04-19T10:30:00",
      "completedAt": "2024-04-19T10:31:15",
      "journalEntriesCount": 42,
      "reportsGenerated": 3
    }
  ]
}
```

**Error Responses:**
- `404` - Business not found
- `401/403` - Invalid or missing API key

### 3. Get Job Status

`GET /api/accounting/jobs/{task_id}?businessId={businessId}`

**Response:**
```json
{
  "taskId": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
  "businessId": "60d5ecb8b6f3c72e7c8e4a5b",
  "periodStart": "2024-01-01T00:00:00",
  "periodEnd": "2024-01-31T23:59:59",
  "status": "completed",
  "progressPercent": 100,
  "startedAt": "2024-04-19T10:30:00",
  "completedAt": "2024-04-19T10:31:15",
  "journalEntriesCount": 42,
  "reportsGenerated": 3
}
```

**Status values:** `pending`, `processing`, `completed`, `failed`, `cancelled`

**Error Responses:**
- `404` - Task not found or business not found

### 4. Get Job Results

`GET /api/accounting/jobs/{task_id}/results?businessId={businessId}`

**Response (Full Results):**
```json
{
  "taskId": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
  "businessId": "60d5ecb8b6f3c72e7c8e4a5b",
  "status": "completed",

  "totalRevenue": 12500.00,
  "totalExpenses": 5000.00,
  "grossProfit": 7500.00,
  "netProfit": 6750.00,
  "accountsReceivable": 2500.00,
  "accountsPayable": 1000.00,
  "cashPosition": 8500.00,

  "taxCalculations": [
    {
      "taxType": "VAT",
      "jurisdiction": "Tunisia",
      "taxableAmount": 12500.00,
      "taxRate": 0.19,
      "taxAmount": 2375.00
    }
  ],

  "aiInsights": "Revenue up 15% vs last month. Review A/R aging.",
  "recommendations": ["Follow up on 3 overdue invoices"],
  "anomaliesDetected": [
    {
      "id": "A-1001",
      "type": "duplicate_invoice",
      "severity": "medium",
      "description": "Detected duplicate invoices INV-2024-007 and INV-2024-008 (same invoice number, different amounts).",
      "detectedAt": "2024-01-20T09:12:34Z",
      "affectedRecords": ["INV-2024-007", "INV-2024-008"],
      "suggestedAction": "Review the invoices, confirm the correct record, mark the duplicate and adjust journal entries if needed."
    },
    {
      "id": "A-1002",
      "type": "negative_revenue",
      "severity": "high",
      "description": "Negative revenue detected for invoice INV-2024-015 indicating a possible refund or data entry error.",
      "detectedAt": "2024-01-25T14:05:00Z",
      "affectedRecords": ["INV-2024-015"],
      "suggestedAction": "Verify the invoice lines and issue a credit note or correct the invoice amount."
    }
  ],

  "journalEntries": [
    {
      "date": "2024-01-15T00:00:00",
      "account": "Accounts Receivable",
      "debit": 12500.00,
      "credit": 0.00,
      "description": "Invoice INV-2024-001",
      "invoiceId": "INV-2024-001",
      "metadata": {}
    }
  ],
  "totalJournalEntries": 42
}
```

**Error Responses:**
- `400` - Job not completed yet (check status first)
- `404` - Task not found or business not found

### 5. Cancel Accounting Job

`DELETE /api/accounting/jobs/{task_id}?businessId={businessId}`

Cancel a pending or processing accounting job. Cannot cancel completed, failed, or already cancelled jobs.

**Response (Success):**
```json
{
  "taskId": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
  "status": "cancelled",
  "message": "Accounting job cancelled successfully",
  "previousStatus": "pending"
}
```

**Error Responses:**
- `400` - Cannot cancel job (already completed, failed, or cancelled)
- `404` - Task not found or business not found
- `401/403` - Invalid or missing API key

### 6. Get Accounting History

`GET /api/accounting/business/{business_id}/history?limit=10`

Returns list of all accounting periods for a business.

**Response:**
```json
{
  "businessId": "60d5ecb8b6f3c72e7c8e4a5b",
  "tasks": [
    {
      "taskId": "60d5ecb8b6f3c72e7c8e4a5b_20240201_20240229",
      "periodStart": "2024-02-01T00:00:00",
      "periodEnd": "2024-02-29T23:59:59",
      "status": "completed",
      "completedAt": "2024-03-01T10:15:30"
    }
  ]
}
```

### 7. Get All Accountant Work

`GET /api/accounting/business/{business_id}/work`

Comprehensive work log with full details.

**Query params:** `start_date`, `end_date`, `status`

**Response:**
```json
{
  "businessId": "60d5ecb8b6f3c72e7c8e4a5b",
  "databaseName": "business_60d5ecb8b6f3c72e7c8e4a5b_db",
  "summary": {
    "totalAccountingPeriods": 12,
    "completed": 12,
    "pending": 0,
    "processing": 0,
    "failed": 0,
    "totalJournalEntriesGenerated": 240,
    "totalRevenueProcessed": 150000.00
  },
  "accountingPeriods": [
    {
      "taskId": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
      "periodStart": "2024-01-01T00:00:00",
      "periodEnd": "2024-01-31T23:59:59",
      "status": "completed",
      "createdAt": "2024-02-01T09:00:00",
      "startedAt": "2024-02-01T09:00:05",
      "completedAt": "2024-02-01T09:02:30",
      "journalEntriesCount": 20,
      "taxCalculationsCount": 3,
      "reportsCount": 2,
      "hasAiInsights": true,
      "recommendationsCount": 3,
      "financialSummary": {
        "totalRevenue": 12500.00,
        "totalExpenses": 5000.00,
        "grossProfit": 7500.00,
        "netProfit": 6750.00,
        "accountsReceivable": 2500.00,
        "accountsPayable": 1000.00,
        "cashPosition": 8500.00
      }
    }
  ]
}
```

### 8. Get Tunisian Tax Summary
`GET /api/accounting/business/{business_id}/taxes?year=2024`

Returns a persisted tax summary for the given year. If a summary does not exist the endpoint returns `404` and instructs the caller to POST to the calculate endpoint to generate and persist the summary.

**Response:**
```json
{
  "businessId": "60d5ecb8b6f3c72e7c8e4a5b",
  "businessName": "Acme Corp",
  "year": 2024,
  "currency": "TND",
  "summary": {
    "annualVatTotal": 28500.00,
    "annualCorporateTax": 13500.00,
    "annualWithholdingTax": 2250.00,
    "totalTaxLiability": 44250.00
  },
  "vatBreakdown": {
    "standardRate19Percent": 28500.00,
    "reducedRate13Percent": 0.00,
    "reducedRate7Percent": 0.00
  },
  "monthlyDetails": [
    {
      "month": 1,
      "period": "01/2024",
      "vatStandard19": 2375.00,
      "vatReduced13": 0.00,
      "vatReduced7": 0.00,
      "vatTotal": 2375.00,
      "taxableIncome": 7500.00,
      "corporateTaxDue": 1125.00,
      "withholdingTax": 187.50,
      "totalTaxLiability": 3631.25,
      "dueDate": "2024-02-28T00:00:00"
    }
  ],
  "taxCalendar": [
    {
      "period": "01/2024",
      "dueDate": "2024-02-28T00:00:00",
      "description": "VAT due for January 2024"
    }
  ],
  "notes": [
    "VAT (TVA) is due by the 28th of the following month",
    "Standard VAT rate: 19%",
    "Reduced rates: 13% (transport, tourism), 7% (medical, education)",
    "Corporate tax (IS): 15% for SMEs, 25% for larger companies",
    "Withholding tax: 1.5% on B2B transactions"
  ]
}
```

### API Endpoint Summary

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/` | Service info | No |
| GET | `/api/health` | Basic health check | No |
| GET | `/api/health/ready` | Readiness probe | No |
| POST | `/api/accounting/jobs` | Create accounting job | Yes |
| GET | `/api/accounting/jobs` | List jobs | Yes |
| GET | `/api/accounting/jobs/{task_id}` | Get job status | Yes |
| GET | `/api/accounting/jobs/{task_id}/results` | Get job results | Yes |
| DELETE | `/api/accounting/jobs/{task_id}` | Cancel job | Yes |
| GET | `/api/accounting/business/{business_id}/history` | Accounting history | Yes |
| GET | `/api/accounting/business/{business_id}/work` | All work details | Yes |
| GET | `/api/accounting/business/{business_id}/taxes` | Tax summary (returns 404 if not calculated) | Yes |
| POST | `/api/accounting/business/{business_id}/taxes/calculate` | Calculate and persist Tunisian tax summary for a year | Yes |

### Security

- All `/api/accounting/*` endpoints are protected by an API key check. Provide the API key in the `X-API-Key` header when calling protected endpoints. The key is configured via the `API_KEY` environment variable (see `app/config.py`). If `API_KEY` is not set the service will run unprotected but log a warning.
- An optional `Authorization: Bearer <token>` JWT may be provided; the service accepts a bearer token but does not perform full JWT validation by default (Accountia API should validate tokens). Security behavior is implemented in `app/core/security.py`.

### Task Queue & Worker

- To enable Redis-backed queueing set `USE_TASK_QUEUE=true` and configure `REDIS_URL`.
- Enqueued jobs are pushed to Redis list key `accounting_job_queue` by `app/tasks/queue.py`.
- A simple worker is provided at `scripts/worker.py`. Run it from the project root (activate your virtualenv first):

```bash
source venv/bin/activate
python -m scripts.worker
```

- The `scripts/estimate_eta.py` script computes average seconds-per-journal-entry from historical completed tasks and helps tune the `estimated_seconds` value used when creating jobs.

### Training / Admin Endpoints (optional)

There is an administrative training router implemented at `app/routers/training.py` that provides utilities for generating synthetic training data, exporting business data for training, and starting fine-tuning. Important: this router is not mounted in the application by default — `app/main.py` currently includes only the accounting and health routers. To expose the training endpoints, add the following to `app/main.py`:

```py
from app.routers import training
app.include_router(training.router, prefix="/api/training", tags=["Training"])
```

If mounted, the key training endpoints are:

- `GET /api/training/status` — Returns current model status and which model path is in use.
- `POST /api/training/data/generate` — Generate synthetic training data. Body: `{ "num_examples": 1000, "output_file": "training_data.jsonl" }`.
- `POST /api/training/fine-tune` — Start fine-tuning on a previously generated training file. This runs in background; response includes a `jobId`.
- `POST /api/training/reload` — Reload model weights (use after fine-tuning).
- `GET /api/training/data/samples?n=5` — Return sample training examples.
- `POST /api/training/data/export-business` — Export invoices/products for a `businessId` and produce training examples; optionally starts fine-tuning when `autoFineTune=true` and there's enough data.

Example flow (if training router mounted):

```bash
# Generate synthetic training data
curl -X POST http://localhost:8000/api/training/data/generate \
  -H "Content-Type: application/json" \
  -d '{"num_examples":1000, "output_file":"training_data.jsonl"}'

# Start fine-tuning
curl -X POST http://localhost:8000/api/training/fine-tune \
  -H "Content-Type: application/json" \
  -d '{"training_file":"training_data.jsonl","num_epochs":3}'
```

I can enable these routes in the app and add detailed request/response examples if you want.

### Tax Rates Reference

| Tax Type | Rate | Applies To |
|----------|------|------------|
| VAT Standard | 19% | Most goods/services |
| VAT Reduced | 13% | Transport, tourism |
| VAT Reduced | 7% | Medical, education |
| Corporate Tax | 15% | SMEs |
| Corporate Tax | 25% | Larger companies |
| Withholding | 1.5% | B2B transactions |

### Integration Flow Example

```bash
# 1. Create job
curl -X POST http://localhost:8000/api/accounting/jobs \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"businessId":"60d5ecb8b6f3c72e7c8e4a5b","periodStart":"2024-01-01T00:00:00Z","periodEnd":"2024-01-31T23:59:59Z"}'

# 2. Poll for completion
curl "http://localhost:8000/api/accounting/jobs/{task_id}?businessId=60d5ecb8b6f3c72e7c8e4a5b" \
  -H "X-API-Key: your_api_key"

# 3. Get results
curl "http://localhost:8000/api/accounting/jobs/{task_id}/results?businessId=60d5ecb8b6f3c72e7c8e4a5b" \
  -H "X-API-Key: your_api_key"

# 4. List all jobs for a business
curl "http://localhost:8000/api/accounting/jobs?businessId=60d5ecb8b6f3c72e7c8e4a5b&limit=10" \
  -H "X-API-Key: your_api_key"

# 5. Cancel a pending/processing job
curl -X DELETE "http://localhost:8000/api/accounting/jobs/{task_id}?businessId=60d5ecb8b6f3c72e7c8e4a5b" \
  -H "X-API-Key: your_api_key"

# 6. Get tax summary
curl "http://localhost:8000/api/accounting/business/60d5ecb8b6f3c72e7c8e4a5b/taxes?year=2024" \
  -H "X-API-Key: your_api_key"
```

## Setup

### Local Development

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Copy environment file:**
```bash
cp .env.example .env
# Edit .env with your MongoDB URI and Groq API key
```

3. **Generate training data (optional):**
```bash
python generate_training_data.py --examples 1000
```

4. **Run the service:**
```bash
uvicorn app.main:app --reload
```

### Docker

```bash
docker-compose up -d
```

This starts:
- AI Accountant API (port 8000)
- MongoDB (port 27017)
- Redis (port 6379)

## Training the Model (Offline)

Training is done **offline** before deploying the service. The API only exposes accounting endpoints.

### Option 1: Synthetic Data
```bash
python train_model.py --generate --train
```

### Option 2: Real Business Data
```bash
python train_model.py \
	--business-id 60d5ecb8b6f3c72e7c8e4a5b \
	--business-name "My Company" \
	--train
```

### Training Options
```bash
# More examples
python train_model.py --generate --num-examples 5000 --train

# More epochs (better quality, slower)
python train_model.py --generate --train --epochs 5

# Custom output location
python train_model.py --generate --train --model-output models/my_model
```

## How It Works

### Accounting Process

1. **Request Received**: Business provides date range (e.g., Jan 1-31)
2. **Data Fetch**: Service reads invoices from tenant's MongoDB collection
   
	 Invoice schema (what the engine expects):

	 - `issuerBusinessId`: ObjectId or string matching the `business_id`.
	 - `issuedDate`: ISO datetime when the invoice was issued.
	 - `totalAmount`: numeric total for the invoice (preferred).
		 - Older/alternate fields: `total` or `total_amount` will be accepted.
	 - `lineItems` (preferred) or `lines`: array of line objects with at least:
		 - `productId` (ObjectId/string), `productName`, `quantity`, `unitPrice`, `amount`.
	 - `status`: one of `DRAFT`, `ISSUED`, `PAID`, `PARTIAL`, `OVERDUE`, `DISPUTED`.

	 Example invoice document (simplified):

	 ```json
	 {
		 "_id": "69d5b00eab5a83676147f71a",
		 "issuerBusinessId": "69d596205c7d958b7c5f0709",
		 "issuedDate": "2026-04-08T00:00:00Z",
		 "status": "ISSUED",
		 "lineItems": [
			 {"productId": "69d596f25c7d958b7c5f074a", "productName": "HP pcs", "quantity": 2, "unitPrice": 2000, "amount": 4000}
		 ],
		 "totalAmount": 4000
	 }
	 ```

	 Notes: the engine normalizes `totalAmount` and `lineItems` at runtime and will fall back to alternate field names if necessary.
3. **Journal Entries**: Generates double-entry bookkeeping entries
	 - Revenue recognition (accrual basis)
	 - COGS matching
	 - A/R tracking
	 - Tax liabilities
4. **Tax Calculation**: Computes VAT/Sales tax by rate
5. **Financial Summary**: Calculates P&L metrics
6. **AI Analysis**: LLM generates insights and recommendations
7. **Results Saved**: All data written back to `accounting_tasks` collection

### Multi-Tenancy

- Reads from business-specific tenant database
- Results stored in same tenant DB (isolated per business)
- Task ID: `{business_id}_{start_date}_{end_date}`

### Journal Entry Logic

| Invoice Status | Debit | Credit |
|----------------|-------|--------|
| **PAID** | Cash/Bank (total) | Revenue (total) |
| | COGS | Inventory |
| **PARTIAL** | Cash/Bank (paid) | Revenue (total) |
| | A/R (remaining) | |
| **ISSUED/OVERDUE** | A/R (total) | Revenue (total) |

### Integration with Accountia API

From a backend (e.g. NestJS), call the AI Accountant by sending the business's `business_id` and the ISO period range. The service requires the `X-API-Key` header for service-to-service auth (and supports an optional bearer `Authorization` JWT). Do NOT send `database_name`—the service resolves the tenant DB from the platform.

```typescript
// In your business controller (example - NestJS)
@Post(':id/accounting')
async runAccounting(
	@Param('id') businessId: string,
	@Body() dto: { startDate: string; endDate: string },
) {
	const response = await fetch('http://localhost:8000/api/accounting/jobs', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			'X-API-Key': process.env.ACCOUNTIA_API_KEY,
			// optional: 'Authorization': `Bearer ${token}` if you use JWTs
		},
    body: JSON.stringify({
      businessId: businessId,
      periodStart: dto.startDate,
      periodEnd: dto.endDate,
    }),
	});

	if (!response.ok) {
		throw new Error(`Accounting API error: ${response.statusText}`);
	}

	return response.json();
}
```

## Training Data Format

The fine-tuning uses Alpaca-style format:

```json
{
	"instruction": "Calculate revenue for these invoices: ...",
	"input": "",
	"output": "The total revenue is $10,000..."
}
```

Scenarios covered:
- Revenue recognition (accrual vs cash)
- COGS calculation
- Tax computation
- Journal entry generation
- Financial analysis
- Anomaly detection

## Model Details

- **Base Model**: Qwen/Qwen2.5-1.5B-Instruct (works on 4GB GPU)
- **Fine-tuning**: LoRA (Low-Rank Adaptation)
- **Quantization**: 8-bit (with `load_in_8bit=true`)
- **Fallback**: Groq API (llama-3.3-70b-versatile) when local model unavailable

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `MONGO_URI` | MongoDB connection string (including platform DB name) | Yes |
| `GROQ_API_KEY` | Groq API key for fallback inference | No |
| `USE_FINE_TUNED` | Use locally fine-tuned model if available (`true`/`false`) | No |
| `DEBUG` | Enable debug mode (enables permissive CORS and extra logs) | No |

Additional configuration options (set via `.env` or environment):

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_URL` | Redis connection string used for the task queue and caching | `redis://localhost:6379/0` |
| `USE_TASK_QUEUE` | When `true` newly created accounting jobs are enqueued to Redis instead of run inline | `false` |
| `API_KEY` | Service-to-service API key required in `X-API-Key` header for protected endpoints | None (recommended to set) |
| `JWT_SECRET` | Optional secret for validating JWTs (the service accepts Bearer tokens but does not validate by default) | None |
| `BASE_MODEL` | Base LLM identifier used for local inference | `Qwen/Qwen2.5-1.5B-Instruct` |
| `FINE_TUNED_MODEL_PATH` | Path to local fine-tuned model (if `USE_FINE_TUNED=true`) | `./models/accountant-lora` |
| `TRAINING_OUTPUT_DIR` | Directory where fine-tuning output is written | `./models/accountant-lora` |

All settings are defined in `app/config.py` (the `Settings` model). The service reads `.env` by default via `pydantic-settings`.

## Developer Notes: Recent Changes & How to Run

This project has been updated with a number of developer-facing improvements to make accounting jobs reliable, observable, and queueable. The following notes summarize the main changes, how to run the new components, and recommended next steps.

- **Task persistence & multi-tenancy sync**: Jobs are still stored in the platform (Beanie) documents, but create/update paths now also write an idempotent `$set` projection into the tenant database so tenant reads (API endpoints) can immediately see created tasks. This prevents a race where a job created on the platform DB isn't visible to tenant DB reads.

- **Estimated time / ETA**: Jobs store `estimated_seconds` and `estimated_completion` computed at creation time. `GET /api/accounting/jobs` and `GET /api/accounting/jobs/{task_id}` return `estimated_time_remaining` (seconds) derived from `started_at` + `estimated_seconds` when available.

- **Redis task queue + worker**: Optional queueing is supported. Set `USE_TASK_QUEUE=true` to push created jobs to a Redis-backed queue instead of running inline. A simple worker is provided in `scripts/worker.py` which dequeues jobs from `accounting_job_queue` and calls the processing function. The worker uses `structlog` for consistent structured logging.

- **ETA estimator script**: `scripts/estimate_eta.py` computes average seconds-per-journal-entry from completed tasks to produce a data-driven estimator. Run it to generate a recommended `seconds_per_entry` number and integrate it into job creation logic.

- **Indexes & projections**: Tenant DB writes create idempotent indexes for `task_id` (unique) and `(business_id, period_start)` to accelerate list/status queries and ensure uniqueness.

- **Logging & error handling**: Replaced silent `except` blocks with `logger.debug/exception` and standardized structured logging via `structlog` in the worker to avoid TypeError when logging with kwargs.

- **Month-end/tax fixes**: Fixed month-end calculation to use `calendar.monthrange(...)` instead of a fixed `28` day assumption.

- **Security note**: The repository contains `.env.example`. Do NOT commit a live `.env` with secrets. Rotate any secrets exposed during testing; consider removing `.env` from the working tree and using environment-specific secret stores (Vault, AWS SSM, etc.).

How to run the new components

- Start the FastAPI app (dev):

```bash
uvicorn app.main:app --reload
```

- Run the ETA estimator against your DB (prints recommended seconds-per-entry):

```bash
python -m scripts.estimate_eta
```

- Run the Redis worker (ensure `USE_TASK_QUEUE=true` and Redis is reachable):

```bash
# activate venv
source venv/bin/activate
python -m scripts.worker
```

- Create a job (example):

```bash
curl -X POST http://localhost:8000/api/accounting/jobs \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"businessId":"69d596205c7d958b7c5f0709","periodStart":"2024-03-01T00:00:00Z","periodEnd":"2024-03-31T23:59:59Z"}'
```

Notes & recommended next steps

- To enable queueing in production, run one or more instances of `scripts.worker.py` (supervised by systemd, docker-compose, or similar) and set `USE_TASK_QUEUE=true` in the environment. Workers should be colocated with good network link to Redis and MongoDB.
- Run `scripts/estimate_eta.py` periodically (or once) and feed the resulting `seconds_per_entry` into `create_accounting_job` logic to improve ETA accuracy.
- Add Prometheus metrics for: job durations, per-entry processing time, LLM call durations, DB read/write latencies and job queue lengths.
- Add a one-off migration script to backfill tenant DB for any previously created tasks that only exist in the platform DB.
- Rotate secrets and remove any live `.env` from Git history if it was committed.

If you'd like, I can run the ETA script against your local/dev DB and wire the computed value into `create_accounting_job`, add a systemd unit example for the worker, or add Prometheus instrumentation scaffolding.

## Schema Definitions (Full)

Below are the authoritative JSON schemas and examples you should use when building clients against the HTTP API. Note: tenant database documents are persisted in snake_case (see the tenant examples) while API responses use camelCase.

1) AccountingTask (tenant DB document - snake_case)

```json
{
  "business_id": "string",
  "task_id": "string",
  "period_start": "2024-01-01T00:00:00Z",
  "period_end": "2024-01-31T23:59:59Z",
  "status": "completed",
  "progress_percent": 100,
  "started_at": "2024-02-01T09:00:05Z",
  "completed_at": "2024-02-01T09:02:30Z",
  "estimated_seconds": 120,
  "estimated_completion": "2024-02-01T09:02:05Z",
  "journal_entries": [ /* JournalEntry objects */ ],
  "tax_calculations": [ /* TaxCalculation objects */ ],
  "financial_summary": { /* FinancialSummary */ },
  "reports": [],
  "ai_insights": "string",
  "recommendations": [],
  "anomalies_detected": [],
  "created_at": "2024-02-01T09:00:00Z",
  "processed_by": "ai-accountant-v1"
}
```

2) AccountingJobStatusResponse (API response - camelCase)

```json
{
  "taskId": "string",
  "businessId": "string",
  "periodStart": "2024-01-01T00:00:00Z",
  "periodEnd": "2024-01-31T23:59:59Z",
  "status": "processing",
  "progressPercent": 55,
  "startedAt": "2024-02-01T09:00:05Z",
  "completedAt": null,
  "errorMessage": null,
  "journalEntriesCount": 42,
  "reportsGenerated": 3,
  "estimatedSeconds": 120,
  "estimatedCompletion": "2024-02-01T09:02:05Z",
  "estimatedTimeRemaining": 65
}
```

3) AccountingResultsResponse (API response - camelCase)

```json
{
  "taskId": "string",
  "businessId": "string",
  "periodStart": "2024-01-01T00:00:00Z",
  "periodEnd": "2024-01-31T23:59:59Z",
  "status": "completed",
  "totalRevenue": 12500.00,
  "totalExpenses": 5000.00,
  "grossProfit": 7500.00,
  "netProfit": 6750.00,
  "accountsReceivable": 2500.00,
  "accountsPayable": 1000.00,
  "cashPosition": 8500.00,
  "taxCalculations": [
    {
      "taxType": "VAT",
      "jurisdiction": "Tunisia",
      "taxableAmount": 12500.00,
      "taxRate": 0.19,
      "taxAmount": 2375.00,
      "notes": ""
    }
  ],
  "aiInsights": "Revenue up 15% vs last month.",
  "recommendations": ["Follow up on 3 overdue invoices"],
  "anomaliesDetected": [],
  "reports": [],
  "journalEntries": [
    {
      "date": "2024-01-15T00:00:00Z",
      "account": "Accounts Receivable",
      "debit": 12500.00,
      "credit": 0.00,
      "description": "Invoice INV-2024-001",
      "invoiceId": "INV-2024-001",
      "metadata": {}
    }
  ],
  "totalJournalEntries": 42
}
```

4) TaxSummary (API response / persisted document mapping)

The tenant DB stores the persisted tax summary in snake_case under `tax_summaries`. The API responses convert keys to camelCase. Example API response for both GET and POST (calculate) is:

```json
{
  "businessId": "60d5ecb8b6f3c72e7c8e4a5b",
  "businessName": "Acme Corp",
  "year": 2024,
  "currency": "TND",
  "summary": {
    "annualVatTotal": 28500.00,
    "annualCorporateTax": 13500.00,
    "annualWithholdingTax": 2250.00,
    "totalTaxLiability": 44250.00
  },
  "vatBreakdown": {
    "standardRate19Percent": 28500.00,
    "reducedRate13Percent": 0.00,
    "reducedRate7Percent": 0.00
  },
  "monthlyDetails": [ /* per-month breakdown objects */ ],
  "taxCalendar": [ /* calendar entries with dueDate (ISO string) and description */ ],
  "notes": ["VAT (TVA) is due by the 28th of the following month"],
  "createdAt": "2024-02-01T09:05:00Z",
  "lastUpdatedAt": "2024-02-01T09:05:00Z"
}
```

POST /api/accounting/business/{business_id}/taxes/calculate

- Description: Calculate taxes for a given `year` and persist the result in the tenant DB. If a summary already exists the endpoint returns a message indicating the existing summary.
- Parameters: `year` (query param, optional — defaults to current year)
- Body: none

Example request (no body, using query param):

```bash
curl -X POST "http://localhost:8000/api/accounting/business/60d5ecb8b6f3c72e7c8e4a5b/taxes/calculate?year=2024" \
  -H "X-API-Key: your_api_key"
```

Example successful response (created/persisted):

```json
{
  "businessId": "60d5ecb8b6f3c72e7c8e4a5b",
  "businessName": "Acme Corp",
  "year": 2024,
  "summary": {
    "annualVatTotal": 28500.00,
    "annualCorporateTax": 13500.00,
    "annualWithholdingTax": 2250.00,
    "totalTaxLiability": 44250.00
  }
}
```

Example response when a summary already exists:

```json
{
  "message": "Tax summary already exists",
  "businessId": "60d5ecb8b6f3c72e7c8e4a5b",
  "year": 2024
}
```

Notes:

- Numeric monetary values are stored as Decimals in the DB models but API responses use floats for JSON compatibility.
- All timestamps are UTC ISO 8601 strings.

## Error Response Examples (per endpoint)

Each endpoint can return standard JSON error responses with an HTTP status code and `detail` field. Below are explicit examples for common errors.

Common error JSON format:
```json
{
	"detail": "Human-readable error message"
}
```

1) `POST /api/accounting/jobs`
- 400 Invalid period:
```json
HTTP/1.1 400 Bad Request
{
	"detail": "Accounting period cannot exceed 365 days"
}
```
- 404 Business not found:
```json
HTTP/1.1 404 Not Found
{
	"detail": "Business not found for id 69..."
}
```
- 401 Missing API key:
```json
HTTP/1.1 401 Unauthorized
{
	"detail": "API key required. Access denied."
}
```
- 403 Invalid API key:
```json
HTTP/1.1 403 Forbidden
{
	"detail": "Invalid API key. Access denied."
}
```
- 500 Save failure:
```json
HTTP/1.1 500 Internal Server Error
{
	"detail": "Failed to create job: <error message>"
}
```

2) `GET /api/accounting/jobs` (list)
- 404 Business not found:
```json
HTTP/1.1 404 Not Found
{
	"detail": "Business not found for id 69..."
}
```

3) `GET /api/accounting/jobs/{task_id}` (status)
- 404 Task not found:
```json
HTTP/1.1 404 Not Found
{
	"detail": "Task not found"
}
```

4) `GET /api/accounting/jobs/{task_id}/results`
- 404 Task not found:
```json
HTTP/1.1 404 Not Found
{
	"detail": "Task not found"
}
```
- 400 Not completed yet:
```json
HTTP/1.1 400 Bad Request
{
	"detail": "Task not completed. Current status: processing"
}
```

5) `DELETE /api/accounting/jobs/{task_id}`
- 404 Task not found:
```json
HTTP/1.1 404 Not Found
{
	"detail": "Task not found"
}
```
- 400 Cannot cancel:
```json
HTTP/1.1 400 Bad Request
{
	"detail": "Cannot cancel job with status 'completed'. Only pending or processing jobs can be cancelled."
}
```

6) Readiness / health endpoints
- 200 readiness not ready (example):
```json
HTTP/1.1 200 OK
{
	"status": "not_ready",
	"checks": { "mongodb": false, "model": true }
}
```

Implementation notes
- All error responses are raised via FastAPI `HTTPException(detail=...)` and follow the `{"detail":"..."}` schema.
- If you need richer error schemas (codes, types, troubleshooting links), I can add a standardized error model and update all endpoints to return it.

## License

Proprietary - Accountia Platform

