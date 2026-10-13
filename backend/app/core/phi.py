"""PHI minimization helpers.

These masks are for display, logs, and model context. They are not a substitute
for access control or encryption at rest.
"""

import re

PHI_KEYS = {
    "patient_first_name",
    "patient_last_name",
    "patient_name",
    "member_id",
    "subscriber_id",
    "date_of_birth",
    "address",
    "street",
}


def mask_identifier(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    trimmed = value.strip()
    if len(trimmed) <= 4:
        return "****"
    return ("*" * (len(trimmed) - 4)) + trimmed[-4:]


def mask_name(last_name: str | None, first_name: str | None) -> str | None:
    if not last_name and not first_name:
        return None
    last = (last_name or "").strip()
    first = (first_name or "").strip()
    last_mask = (last[:1].upper() + "***") if last else ""
    first_mask = (first[:1].upper() + ".") if first else ""
    return " ".join(part for part in (first_mask, last_mask) if part) or None


def assert_no_phi_payload(payload: object) -> None:
    """Raise if a model-bound payload still carries direct patient identifiers."""
    found: list[str] = []

    def walk(node: object, trail: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key)
                if key_text.lower() in PHI_KEYS and value not in (None, "", [], {}):
                    found.append(f"{trail}.{key_text}" if trail else key_text)
                walk(value, key_text)
        elif isinstance(node, list):
            for item in node:
                walk(item, trail)

    walk(payload, "")
    if found:
        raise ValueError("Refusing model context that still contains PHI fields: " + ", ".join(found))


def redact_text(value: str) -> str:
    """Best-effort redaction for log messages. Do not log raw EDI."""
    redacted = re.sub(r"\b\d{9}\b", "[redacted-id]", value)
    return redacted[:500]
