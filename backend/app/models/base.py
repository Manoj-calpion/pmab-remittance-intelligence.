"""Shared SQLAlchemy types and declarative base."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, Uuid

MONEY = Numeric(14, 2)
RATE = Numeric(10, 6)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class PortableVector(TypeDecorator):
    """JSON embeddings locally, pgvector when the dialect is PostgreSQL."""

    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int = 256) -> None:
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(JSON())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def money_column(*, nullable: bool = False):
    return mapped_column(MONEY, nullable=nullable)


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


__all__ = [
    "Base",
    "JSON",
    "MONEY",
    "PortableVector",
    "String",
    "TimestampMixin",
    "money_column",
    "pk",
    "quantize_money",
    "utcnow",
]
