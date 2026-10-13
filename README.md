# PMAB Remittance Intelligence

Read the 835. Reconcile the money. Name the denial. Show the exposure.

PMAB Remittance Intelligence is an agentic platform for healthcare ERA and EDI X12 835 files. It ingests remittances, parses them with `Decimal` arithmetic, reconciles every claim, classifies denials, and lets five LangGraph agents explain only what the tools already proved.

Central Reach stays read-only. The language model never calculates reimbursement. Missing contracts and missing dates stay missing.

## What it catches

| Signal | How it is decided |
| --- | --- |
| Top denial reasons | CARC and RARC mappings. Contractual write-offs and patient responsibility are not denials. |
| Payer trends | Claim volume, denial rate, denied amount, delays, and underpayment exposure by payer. |
| Payment delays | Approved submission or acceptance date to payment date. Service dates are never used as a substitute. |
| Underpayments | Approved contract rule versus actual reimbursement. No rule means insufficient data. |
| Authorization denials | Adjustments mapped to the authorization category. |
| Coding denials | Adjustments mapped to the coding category. |
| Statistical anomalies | Modified z-score against a historical baseline. An anomaly is a lead, not a confirmed payment error. |

A labeled synthetic load of the checked-in 835 corpus produced:

- 27 parsed files, 1 quarantined malformed file, 1 duplicate
- 117 claims analyzed
- Denial rate **21.4%**
- Denied amount **$3,860.00**
- **$350.00** underpayment variance and **6** delayed payments, both marked `synthetic_demo`
- 1 critical denial-rate anomaly for Synthetic Payer North, stored with `is_financial_error = false`

## Architecture

```text
Central Reach  ->  read-only retrieval  ->  incremental ingest
                                              |
                                              v
                                         original 835
                                              |
                                              v
                                    parser + reconciliation
                                              |
                                              v
                                          PostgreSQL
                                              |
                      +-----------------------+-----------------------+
                      |                       |                       |
               denial engine           payment engine          anomaly detector
                      |                       |                       |
                      +-----------------------+-----------------------+
                                              |
                                              v
                              LangGraph supervisor
                     denial · payment · payer · root cause · insight
                                              |
                                              v
                                    FastAPI  ->  React
```

Money is calculated in Python. Agents call read-only aggregate tools. They have no SQL and no path back into Central Reach.

## Run the demo

Python 3.12 is required. Docker and Node.js are optional. No AWS account is required.

```powershell
cd backend
python -m pip install -e ".[dev]"
cd ..
$env:DEMO_MODE = "true"
$env:LLM_PROVIDER = "mock"
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm install
npm run dev
```

| Surface | Address |
| --- | --- |
| Dashboard | http://127.0.0.1:5173 |
| API | http://127.0.0.1:8000 |
| API reference | http://127.0.0.1:8000/docs |

On an empty database, demo mode ingests `sample_data/synthetic_835`, loads labeled demo contracts, and loads labeled demo submission dates.

Sign in:

| Email | Password | Role |
| --- | --- | --- |
| `analyst@pmab.demo` | `ChangeMe-Demo-Only` | Analyst |
| `admin@pmab.demo` | `ChangeMe-Demo-Only` | Admin |
| `viewer@pmab.demo` | `ChangeMe-Demo-Only` | Viewer |

The login form fills the analyst account while demo mode is on. `docker compose up --build` starts PostgreSQL with pgvector, Redis, the API, a Celery worker, and the dashboard. The worker stays idle unless `USE_CELERY=true`.

```powershell
cd backend
python -m pytest
cd ../frontend
npm test
```

## The agents

The supervisor routes a question to the agents that have evidence, then stops. It does not loop.

1. **Denial intelligence** compares categories, payers, and procedure codes.
2. **Payment intelligence** ranks delays and underpayments and keeps the calculation trace.
3. **Payer intelligence** compares payer behavior and monthly movement.
4. **Root cause** correlates findings and lists missing evidence. A hypothesis is not a confirmed cause.
5. **Insight and reporting** writes the executive narrative from the tool output.

Bedrock is wired and closed. It runs only when `BEDROCK_PHI_APPROVED=true` and a model ID is set. Until then the labeled mock provider narrates the same evidence. A failed Bedrock call is not replaced with a mock answer.

Human review is required when financial exposure reaches the configured threshold. The default is $1,000.00.

## Stack

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, Polars, Celery, Redis, LangGraph, Amazon Bedrock, React, TypeScript, Vite, Tailwind, TanStack Query, Apache ECharts. Local development falls back to SQLite. Production startup refuses SQLite, demo mode, the default JWT secret, and local file storage.

Terraform in `infrastructure/terraform` describes a private VPC, RDS, encrypted S3, ECS Fargate, SQS, Cognito, KMS, and CloudWatch. It has not been applied. Applying it creates billable AWS resources.

## Rules that do not bend

- Central Reach is never modified, posted, corrected, or resubmitted.
- No Central Reach endpoint is invented. The API connector refuses every call until an approved specification exists.
- No payer contract, denial code, payment date, or claim is fabricated.
- Every monetary value uses `Decimal`.
- Every file is validated. Malformed files are quarantined. Duplicates are detected by SHA-256.
- Raw 835 contents are not written to logs. Patient identifiers stay behind `phi:view`.
- This repository does not claim HIPAA compliance.

The open business inputs are listed in `docs/implementation/missing-requirements.md`. Read that file before treating any figure as a recovery demand.
