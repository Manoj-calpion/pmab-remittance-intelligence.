# Requirement traceability

Status after this change. Evidence is a file or test, not a claim of production validation.

| PDD requirement | Implementation | Evidence | Gap | Priority | Change in this pass | Test |
| --- | --- | --- | --- | --- | --- | --- |
| Downloaded 835 ingestion without Central Reach | Parser, directory ingest, single upload | `backend/app/ingestion/pipeline.py`, `backend/app/edi/parser.py` | Live retrieval still client-managed | Done for files | Batch and ZIP upload, retry, error report | `backend/tests/test_batch_upload.py` |
| SHA-256 duplicates, quarantine, watermark | Existing pipeline | `ingest_content`, `ingest_directory` | None for file hash | Preserved | Lifecycle trace on the era record | Existing pipeline test plus batch test |
| Six analytics | Denial, payer, delay, underpayment, authorization, coding | `backend/app/analytics/service.py` | Contracts and submission dates still required for two metrics | Preserved | Paid total, payer count, payment trend, low-volume flag, month-over-month | Existing calculation tests; overview fields covered by batch test |
| Five agents and supervisor | LangGraph graph | `backend/app/agents/graph.py` | Bedrock stays closed until PHI approval | Preserved | Workspace shows the real route after a run | `test_agent_routes_and_answers_from_evidence_only` |
| Decimal money, no invented reimbursement | Payment and denial engines | `backend/app/payments/engine.py` | Approved contracts not supplied | Preserved | UI shows insufficient data | `backend/tests/test_edi_and_calculations.py` |
| Premium black-and-white workspace | React dashboard | `frontend/src` | Browser build not run on this machine because npm is not installed | UI implemented | Design system, ten workspaces, carousels | Frontend formatter tests; production build still needs Node |
| RBAC, PHI masking, audit, read-only connector | Existing security design | `backend/app/core/security.py`, `connectors.py` | Cognito validation and HIPAA review still open | Preserved | Error reports omit raw EDI | API auth test |
| Central Reach API | Connector refuses every call | `CentralReachAPIConnector` | No approved specification | Unchanged on purpose | Settings label the connector as client-managed and not connected | `test_central_reach_connector_is_refused` |

Business inputs that remain unresolved are listed in `missing-requirements.md`. They were not invented in this pass.
