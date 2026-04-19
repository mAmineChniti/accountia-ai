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
│  │  FastAPI + Fine-tuned Llama 3.1 8B (or Groq API)   │   │
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

Service health check. No authentication required.

**Response:**
```json
{
  "service": "Accountia AI Accountant",
  "version": "1.0.0",
  "status": "operational",
  "description": "AI-powered accounting for Tunisian businesses"
}
```

### 1. Create Accounting Job

`POST /api/accounting/jobs`

Starts AI accounting for a business period. The AI looks up the business database, reads invoices, and generates journal entries.

**Headers:**
```
X-API-Key: your_api_key_here
Content-Type: application/json
```

**Request Body:**
```json
{
  "business_id": "60d5ecb8b6f3c72e7c8e4a5b",
  "period_start": "2024-01-01T00:00:00Z",
  "period_end": "2024-01-31T23:59:59Z"
}
```

**Validation:** Period max 365 days, end must be after start.

**Response (New Job):**
```json
{
  "task_id": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
  "status": "pending",
  "message": "Accounting job created for period 2024-01-01 to 2024-01-31",
  "estimated_completion": "~59 seconds"
}
```

**Response (Already Processing):**
```json
{
  "task_id": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
  "status": "processing",
  "message": "Accounting job already in progress."
}
```

**Response (Already Completed):**
```json
{
  "task_id": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
  "status": "completed",
  "message": "Accounting already completed. Use GET /jobs/{task_id} for results."
}
```

**Error Responses:**
- `400` - Invalid period (exceeds 365 days or end before start)
- `404` - Business not found
- `401/403` - Invalid or missing API key

### 2. Get Job Status

`GET /api/accounting/jobs/{task_id}?business_id={business_id}`

**Response:**
```json
{
  "task_id": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
  "business_id": "60d5ecb8b6f3c72e7c8e4a5b",
  "period_start": "2024-01-01T00:00:00",
  "period_end": "2024-01-31T23:59:59",
  "status": "completed",
  "progress_percent": 100,
  "started_at": "2024-04-19T10:30:00",
  "completed_at": "2024-04-19T10:31:15",
  "journal_entries_count": 42,
  "reports_generated": 3
}
```

**Status values:** `pending`, `processing`, `completed`, `failed`

**Error Responses:**
- `404` - Task not found or business not found

### 3. Get Job Results

`GET /api/accounting/jobs/{task_id}/results?business_id={business_id}`

**Response (Full Results):**
```json
{
  "task_id": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
  "business_id": "60d5ecb8b6f3c72e7c8e4a5b",
  "status": "completed",
  
  "total_revenue": 12500.00,
  "total_expenses": 5000.00,
  "gross_profit": 7500.00,
  "net_profit": 6750.00,
  "accounts_receivable": 2500.00,
  "accounts_payable": 1000.00,
  "cash_position": 8500.00,
  
  "tax_calculations": [
    {
      "tax_type": "VAT",
      "jurisdiction": "Tunisia",
      "taxable_amount": 12500.00,
      "tax_rate": 0.19,
      "tax_amount": 2375.00
    }
  ],
  
  "ai_insights": "Revenue up 15% vs last month. Review A/R aging.",
  "recommendations": ["Follow up on 3 overdue invoices"],
  "anomalies_detected": [],
  
  "journal_entries_preview": [
    {
      "date": "2024-01-15T00:00:00",
      "account": "Accounts Receivable",
      "debit": 12500.00,
      "credit": 0.00,
      "description": "Invoice INV-2024-001"
    }
  ],
  "total_journal_entries": 42
}
```

**Error Responses:**
- `400` - Job not completed yet (check status first)
- `404` - Task not found or business not found

### 4. Get Accounting History

`GET /api/accounting/business/{business_id}/history?limit=10`

Returns list of all accounting periods for a business.

**Response:**
```json
{
  "business_id": "60d5ecb8b6f3c72e7c8e4a5b",
  "tasks": [
    {
      "task_id": "60d5ecb8b6f3c72e7c8e4a5b_20240201_20240229",
      "period_start": "2024-02-01T00:00:00",
      "period_end": "2024-02-29T23:59:59",
      "status": "completed",
      "completed_at": "2024-03-01T10:15:30"
    }
  ]
}
```

### 5. Get All Accountant Work

`GET /api/accounting/business/{business_id}/work`

Comprehensive work log with full details.

**Query params:** `start_date`, `end_date`, `status`

**Response:**
```json
{
  "business_id": "60d5ecb8b6f3c72e7c8e4a5b",
  "database_name": "business_60d5ecb8b6f3c72e7c8e4a5b_db",
  "summary": {
    "total_accounting_periods": 12,
    "completed": 12,
    "pending": 0,
    "processing": 0,
    "failed": 0,
    "total_journal_entries_generated": 240,
    "total_revenue_processed": 150000.00
  },
  "accounting_periods": [
    {
      "task_id": "60d5ecb8b6f3c72e7c8e4a5b_20240101_20240131",
      "period_start": "2024-01-01T00:00:00",
      "period_end": "2024-01-31T23:59:59",
      "status": "completed",
      "created_at": "2024-02-01T09:00:00",
      "started_at": "2024-02-01T09:00:05",
      "completed_at": "2024-02-01T09:02:30",
      "journal_entries_count": 20,
      "tax_calculations_count": 3,
      "reports_count": 2,
      "has_ai_insights": true,
      "recommendations_count": 3,
      "financial_summary": {
        "total_revenue": 12500.00,
        "total_expenses": 5000.00,
        "gross_profit": 7500.00,
        "net_profit": 6750.00,
        "accounts_receivable": 2500.00,
        "accounts_payable": 1000.00,
        "cash_position": 8500.00
      }
    }
  ]
}
```

### 6. Get Tunisian Tax Summary

`GET /api/accounting/business/{business_id}/taxes?year=2024`

Calculates VAT, corporate tax, withholding per Tunisian law.

**Response:**
```json
{
  "business_id": "60d5ecb8b6f3c72e7c8e4a5b",
  "business_name": "Acme Corp",
  "year": 2024,
  "currency": "TND",
  "summary": {
    "annual_vat_total": 28500.00,
    "annual_corporate_tax": 13500.00,
    "annual_withholding_tax": 2250.00,
    "total_tax_liability": 44250.00
  },
  "vat_breakdown": {
    "standard_rate_19_percent": 28500.00,
    "reduced_rate_13_percent": 0.00,
    "reduced_rate_7_percent": 0.00
  },
  "monthly_details": [
    {
      "month": 1,
      "period": "01/2024",
      "vat_standard_19": 2375.00,
      "vat_reduced_13": 0.00,
      "vat_reduced_7": 0.00,
      "vat_total": 2375.00,
      "taxable_income": 7500.00,
      "corporate_tax_due": 1125.00,
      "withholding_tax": 187.50,
      "total_tax_liability": 3631.25,
      "due_date": "2024-02-28T00:00:00"
    }
  ],
  "tax_calendar": [
    {
      "period": "01/2024",
      "due_date": "2024-02-28T00:00:00",
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
  -d '{"business_id":"60d5ecb8b6f3c72e7c8e4a5b","period_start":"2024-01-01T00:00:00Z","period_end":"2024-01-31T23:59:59Z"}'

# 2. Poll for completion
curl "http://localhost:8000/api/accounting/jobs/{task_id}?business_id=60d5ecb8b6f3c72e7c8e4a5b" \
  -H "X-API-Key: your_api_key"

# 3. Get results
curl "http://localhost:8000/api/accounting/jobs/{task_id}/results?business_id=60d5ecb8b6f3c72e7c8e4a5b" \
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

## Integration with Accountia API

From NestJS, call the AI Accountant:

```typescript
// In your business controller
@Post(':id/accounting')
async runAccounting(
  @Param('id') businessId: string,
  @Body() dto: AccountingPeriodDto,
) {
  const business = await this.businessService.getById(businessId);
  
  const response = await fetch('http://localhost:8000/api/accounting/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      business_id: businessId,
      database_name: business.databaseName,
      period_start: dto.startDate,
      period_end: dto.endDate,
    }),
  });
  
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

- **Base Model**: Llama 3.1 8B Instruct
- **Fine-tuning**: LoRA (Low-Rank Adaptation)
- **Quantization**: 4-bit (QLoRA)
- **Training**: ~$20 on GPU cloud (Lambda/RunPod)

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `MONGO_URI` | MongoDB connection string | Yes |
| `GROQ_API_KEY` | Groq API for fallback | No |
| `USE_FINE_TUNED` | Use fine-tuned model | No |
| `DEBUG` | Enable debug mode | No |

## License

Proprietary - Accountia Platform
