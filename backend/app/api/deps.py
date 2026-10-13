"""Authentication and authorization dependencies."""

from collections.abc import Callable

import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.core.database import get_db
from app.core.security import PERMISSIONS, decode_access_token
from app.models import User

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise AppError(401, "unauthorized", "Authentication is required.")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(str(payload.get("sub")))
    except (jwt.PyJWTError, ValueError) as exc:
        raise AppError(401, "unauthorized", "The access token is invalid or expired.") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError(401, "unauthorized", "The user is not active.")
    return user


def require_permission(permission: str) -> Callable:
    def dependency(user: User = Depends(get_current_user)) -> User:
        role_name = user.role.name if user.role is not None else ""
        if permission not in PERMISSIONS.get(role_name, set()):
            raise AppError(403, "forbidden", "You do not have permission to perform this action.")
        return user

    return dependency
