# Implementation checklist

## Phase 0 — Architecture

- [x] Inspected the empty repository and started from scratch.
- [x] Recorded the data model, API, security boundaries, and missing business inputs.

## Phase 1 — Foundation

- [x] FastAPI application, configuration, SQLAlchemy models, Alembic initial revision.
- [x] Local SQLite for a demo without Docker; PostgreSQL and pgvector in Docker Compose.
- [x] JWT roles: admin, analyst, reviewer, viewer.
- [x] Health and metadata endpoints.

## Phase 2 — EDI processing

- [x] Synthetic 835 builder and checked-in fixtures, including a malformed file and a duplicate.
- [x] Delimiter-aware parser for the required 835 segments.
- [x] Decimal reconciliation for service lines, claims, patient responsibility, and provider-level adjustments.
- [x] SHA-256 duplicate detection, quarantine, and source identifiers.
- [x] Original bytes stored through the local storage adapter. S3 is used only when `STORAGE_BACKEND=s3`.

## Phase 3 — Financial analytics

- [x] Denial categories and CARC mappings. Contractual and patient-responsibility adjustments are not denials.
- [x] Payment delays only from approved or explicitly synthetic submission dates.
- [x] Underpayments only from approved rules, or labeled synthetic rules in demo mode.
- [x] Modified z-score anomalies with minimum sample checks. Isolation Forest runs only at the configured sample size.
- [x] Anomalies are flagged as statistical, not confirmed financial errors.

## Phase 4 — Agents

- [x] LangGraph supervisor with denial, payment, payer, root-cause, and insight nodes.
- [x] Read-only tools. No agent SQL.
- [x] Mock provider that repeats evidence. Bedrock provider that refuses until PHI approval and does not fall back to the mock.
- [x] Local knowledge retrieval over synthetic, unapproved samples.

## Phase 5 — Dashboard and reporting

- [x] React routes for overview, denials, payments, payers, authorization, coding, investigation, alerts, processing, reports, and settings.
- [x] CSV, Excel, and PDF aggregate exports with permission checks.
- [x] Browser pass of the dashboard on a portable Node.js runtime: login, overview, denials, payments, authorization, coding, investigation, alerts, processing, settings, and the insight on the overview.

## Phase 6 — AWS definitions

- [x] Terraform for VPC, private RDS, encrypted S3, ECS Fargate, ALB, SQS, Cognito, Secrets Manager, KMS, CloudWatch, and a scheduler.
- [ ] CloudFront distribution and Cognito token validation in the API.
- [ ] No AWS resources were created.

## Verification already run

- [x] Parser and reconciliation on all synthetic fixtures, including six months of history.
- [x] `pytest` in `backend`: 16 tests passed. Frontend Vitest: 2 tests passed. Production build succeeded.
- [x] Incremental ingestion reports files already stored as `skipped_known` instead of an empty run.
- [x] Demo seed: 27 parsed, 1 quarantined, 1 duplicate, 117 claims, denial rate 0.213675, denied amount 3860.00, synthetic underpayment 350.00, 6 synthetic delays, 1 critical anomaly with `is_financial_error=false`.
