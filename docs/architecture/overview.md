# Architecture

Central Reach, or a local synthetic inbox, lands original 835 bytes in object storage. A deterministic pipeline parses, reconciles, and stores claims, service lines, adjustments, and provider-level adjustments in PostgreSQL. Analytics and alerts read those tables. LangGraph agents may call only those read-only analytics functions. FastAPI serves the React dashboard.

```text
Source connector (read-only)
  -> hash, store original, parse, reconcile
  -> PostgreSQL
  -> denial, delay, underpayment, and anomaly services
  -> LangGraph tools
  -> FastAPI
  -> React
```

The parser raises on structural EDI errors and the file is quarantined. An out-of-balance file is still stored, with a failed reconciliation result. Duplicate SHA-256 content does not create a second set of claims.

AI text is produced from tool evidence. If Bedrock is selected before PHI approval, the investigation returns an error and the mock provider is not substituted.

See `missing-requirements.md` for the business inputs that are still absent.
