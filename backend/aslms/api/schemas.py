"""Request and response shapes of the auth, user, access, office and designation endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from aslms.domain.reference import OfficeKind, Permission, Role


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
    is_active: bool = True

    @classmethod
    def from_office(cls, office: Any) -> OfficeOut:
        return cls(
            id=office.id,
            code=office.code,
            name=office.name,
            kind=str(office.kind.value),
            path=office.path,
            is_active=office.is_active,
        )


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


# ------------------------------------------------------------------------------------------------ offices


class OfficeCountsOut(BaseModel):
    children: int
    users: int
    ownership: int
    custody: int


class OfficeNodeOut(OfficeOut):
    tier: str
    depth: int
    users_active: int
    children: list[OfficeNodeOut] = Field(default_factory=list)


class OfficeDetailOut(OfficeOut):
    tier: str
    depth: int
    parent_code: str | None
    notes: str | None
    deactivated_at: datetime | None
    valid_from: date
    valid_to: date | None
    created_at: datetime
    updated_at: datetime
    counts: OfficeCountsOut


class OfficeCreateIn(BaseModel):
    code: str = Field(
        min_length=2,
        max_length=40,
        description="the Secretariat's code, upper-cased, immutable; `<PARENT>-<CHILD>` is the convention",
    )
    name: str = Field(min_length=1, max_length=200)
    kind: OfficeKind
    parent_code: str = Field(min_length=1, max_length=40)
    notes: str | None = Field(None, max_length=4000)
    valid_from: date | None = None


class OfficePatchIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    notes: str | None = Field(None, max_length=4000)
    valid_from: date | None = None


class DepartmentAdminIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    designation: str | None = Field(None, max_length=200)
    designation_id: uuid.UUID | None = None
    mobile: str | None = Field(None, max_length=20)


class DesignationOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    sort_order: int
    is_active: bool


class DesignationCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    sort_order: int | None = Field(None, ge=0, le=100000)


class DesignationPatchIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    sort_order: int | None = Field(None, ge=0, le=100000)
