# Missing business requirements

These items are intentionally unresolved. The software refuses to invent them.

1. Central Reach access method. No approved API, SFTP, or file-drop specification was provided. `CentralReachAPIConnector` has no endpoints and returns an error even if the feature flag is turned on.
2. PMAB file naming. `STORED_FILENAME_PATTERN` defaults to `PLUTUS_{date}_{original}_{hash}.edi`. That is a platform default, not confirmation of the organization's PLUTUS_DATE convention.
3. Denial-amount definition. Denied amount is the sum of adjustments whose active mapping says `is_denial=true`. Contractual and patient-responsibility adjustments are excluded. Reversals are excluded from the denial rate. Partial denials count as denied claims. Finance needs to confirm this definition.
4. CARC and RARC catalog. The shipped labels are internal operational text, not the copyrighted X12 code list. Load the organization's current licensed list before production.
5. Payer contracts and fee schedules. No approved contract was supplied. Underpayment status is `insufficient_data` unless an approved rule is stored. Demo rules are `source_label=synthetic_demo` and `is_approved=false`.
6. Claim submission and acceptance dates. The 835 does not reliably contain them. Delay status is `insufficient_data` unless `claim_submission_events` has an approved date. Service dates are never copied into submission dates.
7. Coordination of benefits. Secondary and tertiary claims are not compared with a primary fee schedule.
8. Interest, prompt-pay discounts, and sequestration. They are retained when present and are not forced into the payment-balance formula.
9. Payment-delay threshold. The default is 30 days and is configurable.
10. Human-review threshold. Investigations at or above `HUMAN_REVIEW_EXPOSURE_THRESHOLD` (default 1000.00) stay in `pending_human_review`.
11. HIPAA, BAA, Bedrock model, and Region approval. PHI is not sent to Bedrock until `BEDROCK_PHI_APPROVED=true`. The local embedder is a token hash for demo retrieval, not a clinical embedding model.
12. Cognito. Terraform can create a user pool. The running API uses local JWT until Cognito token validation is implemented and reviewed.
13. Field-level encryption and retention. AWS KMS covers the Terraform data stores. Local SQLite is a development store. Retention periods were not specified.
14. Approved payer-policy documents. The knowledge base contains synthetic samples marked `is_approved=false`. Root-cause text will not cite them as payer policy.
15. Production readiness. This build has automated tests and a local demo. It has not had a HIPAA review, a payer-contract review, or an AWS deployment.
