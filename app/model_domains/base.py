from __future__ import annotations

from enum import StrEnum
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class UserRole(StrEnum):
    PARTICIPANT = "participant"
    AMBASSADOR = "ambassador"
    COORDINATOR = "coordinator"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"

class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"
    DELETED = "deleted"
    DELETED_PERMANENT = "deleted_permanent"
