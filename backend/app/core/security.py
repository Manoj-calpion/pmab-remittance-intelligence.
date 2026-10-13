"""Local JWT authentication and role checks.

Amazon Cognito is the intended production identity provider. The local JWT
issuer exists so the demo and automated tests can run without an AWS account.
It must not be treated as the production authentication design.
"""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings

PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "analytics:read",
        "remittances:read",
        "remittances:ingest",
        "claims:read",
        "phi:view",
        "alerts:write",
        "reports:export",
        "ai:investigate",
        "settings:write",
        "audit:read",
        "jobs:run",
    },
    "analyst": {
        "analytics:read",
        "remittances:read",
        "remittances:ingest",
        "claims:read",
        "alerts:write",
        "reports:export",
        "ai:investigate",
        "audit:read",
        "jobs:run",
    },
    "reviewer": {
        "analytics:read",
        "remittances:read",
        "claims:read",
        "alerts:write",
        "ai:investigate",
        "audit:read",
    },
    "viewer": {
        "analytics:read",
        "remittances:read",
        "claims:read",
    },
}


def hash_password(password: str, *, iterations: int | None = None, salt: bytes | None = None) -> str:
    settings = get_settings()
    rounds = iterations if iterations is not None else settings.hash_iterations
    salt_bytes = salt or uuid.uuid4().bytes
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, rounds)
    return f"pbkdf2_sha256${rounds}${salt_bytes.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds_text, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hash_password(password, iterations=int(rounds_text), salt=bytes.fromhex(salt_hex))
    return hmac.compare_digest(candidate, stored)


def create_access_token(*, user_id: uuid.UUID, email: str, role: str, settings: Settings | None = None) -> str:
    active = settings or get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=active.jwt_exp_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "permissions": sorted(PERMISSIONS.get(role, set())),
        "exp": expire,
    }
    return jwt.encode(payload, active.jwt_secret, algorithm=active.jwt_algorithm)


def decode_access_token(token: str, settings: Settings | None = None) -> dict:
    active = settings or get_settings()
    return jwt.decode(token, active.jwt_secret, algorithms=[active.jwt_algorithm])


def authenticate(db: Session, email: str, password: str) -> tuple[str, object] | None:
    from app.models import User

    user = db.scalar(select(User).where(User.email == email.lower().strip(), User.is_active.is_(True)))
    if user is None:
        return None
    supplied = password if verify_password(password, user.password_hash) else password.strip()
    if not verify_password(supplied, user.password_hash):
        return None
    role_name = user.role.name if user.role is not None else "viewer"
    token = create_access_token(user_id=user.id, email=user.email, role=role_name)
    return token, user
