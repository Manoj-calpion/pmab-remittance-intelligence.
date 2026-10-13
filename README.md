# PMAB Remittance Intelligence

Local ERA/835 platform for parsing remittances, reconciling payments, classifying denials, and explaining the results. Financial amounts are calculated in Python with `Decimal`. The language model only narrates tool output.

Central Reach is read-only and is not connected. The API connector refuses every call until an approved specification and credentials exist. Do not apply the Terraform configuration unless you explicitly intend to create AWS resources.

## Run the local demo

Python 3.12 is required. Docker and Node.js are optional.

```powershell
cd backend
python -m pip install -e ".[dev]"
cd ..
$env:DEMO_MODE = "true"
$env:LLM_PROVIDER = "mock"
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

On an empty database, demo mode ingests the synthetic 835 files in `sample_data/synthetic_835` and loads labeled demo contracts and submission dates. Open the dashboard at http://127.0.0.1:5173. http://127.0.0.1:8000 is the API: `/` links to the dashboard, and `/docs` is the API reference.

Demo sign-in, only when `DEMO_MODE=true`:

- Email: `analyst@pmab.demo`
- Password: `ChangeMe-Demo-Only`

`admin@pmab.demo` and `viewer@pmab.demo` use that same password. The login form fills both values when demo mode is on.

The dashboard is in `frontend`. From that directory, `npm install`, `npm test`, and `npm run dev` serve it at http://localhost:5173. The Vite server proxies `/api` to port 8000.

`docker compose up --build` starts PostgreSQL with pgvector, Redis, the API, a Celery worker, and the dashboard. It does not require an AWS account. The worker is idle unless `USE_CELERY=true`.

## What the demo calculated

A full synthetic load produced 27 parsed files, 1 quarantined malformed file, and 1 duplicate. The API then reported 117 claims analyzed, a denial rate of 0.213675, and a denied amount of 3860.00. Six payment delays and 350.00 of underpayment variance were returned with basis `synthetic_demo`. One critical denial-rate anomaly was raised for Synthetic Payer North and stored with `is_financial_error=false`.

Contractual CARC 45 and patient-responsibility amounts are not counted as denials. Missing approved submission dates and missing approved contract

The current suite covers EDI parsing, reconciliation, denial classification, delay and underpayment rules, anomaly thresholds, duplicate and quarantine handling, API authentication, report authorization, agent routing, and the Bedrock approval guard.

## Production boundaries

- Set `ENVIRONMENT=production`, `DEMO_MODE=false`, a real `JWT_SECRET`, PostgreSQL, and `STORAGE_BACKEND=s3`.
- Leave `BEDROCK_PHI_APPROVED=false` until the BAA, Region, model, and HIPAA review are complete. The Bedrock provider then refuses the call. It does not fall back to the mock.
- Leave `CENTRAL_REACH_API_ENABLED=false` until the approved API or SFTP specification is available.
- Terraform in `infrastructure/terraform` is a starting definition. It has not been applied.

See `docs/implementation/missing-requirements.md` before treating any result as a recovery demand or a production control.
