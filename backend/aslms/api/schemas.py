"""Request and response shapes of the auth, user and access endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from aslms.domain.reference import Permission, Role


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    device_label: str | None = Field(None, max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=400)


class OfficeOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    path: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    office: OfficeOut
    designation: str | None
    mobile: str | None
    is_active: bool
    must_confirm_profile: bool
    last_login_at: datetime | None
    created_at: datetime


class MeOut(BaseModel):
    user: UserOut
    functions: list[Permission]


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserCreateIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    role: Role
    office_code: str = Field(min_length=1, max_length=40)
    designation: str | None = Field(None, max_length=200)
    designation_id: uuid.UUID | None = None
    mobile: str | None = Field(None, max_length=20)
    functions: list[Permission] = Field(
        default_factory=list, description="extra functions granted at creation"
    )


class UserPatchIn(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=200)
    designation: str | None = Field(None, max_length=200)
    designation_id: uuid.UUID | None = None
    mobile: str | None = Field(None, max_length=20)


class TypeIn(BaseModel):
    role: Role


class PasswordIn(BaseModel):
    password: str = Field(min_length=10, max_length=200)


class OverrideIn(BaseModel):
    effect: str | None = Field(None, pattern="^(grant|deny)$", description="grant, deny, or null to reset")
    reason: str | None = Field(None, max_length=500)


class OverrideOut(BaseModel):
    permission: Permission
    effect: str
    is_active: bool
    granted_by_user_id: uuid.UUID | None
    reason: str | None
    valid_to: datetime | None = None


class UserFunctionsOut(BaseModel):
    user_id: uuid.UUID
    role: Role
    functions: list[Permission]
    overrides: list[OverrideOut]


class PermissionOut(BaseModel):
    code: Permission
    module: str
    label: str
    description: str | None
    is_active: bool


class MatrixEntryIn(BaseModel):
    enabled: bool
