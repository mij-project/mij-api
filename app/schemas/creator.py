from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional, List
from datetime import datetime


class CreatorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    first_name_kana: Optional[str] = Field(None, max_length=50)
    last_name_kana: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=200)
    phone_number: str = Field(min_length=10, max_length=15)
    birth_date: Optional[datetime] = None
    gender_slug: Optional[List[str]] = Field(None, max_length=100)


class CreatorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    first_name_kana: Optional[str] = Field(None, max_length=50)
    last_name_kana: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=200)
    phone_number: Optional[str] = Field(None, min_length=10, max_length=15)
    birth_date: Optional[datetime] = None
    platform_fee_percent: Optional[int] = Field(None, ge=0, le=100)


class CreatorOut(BaseModel):
    user_id: UUID
    name: Optional[str]
    first_name_kana: Optional[str]
    last_name_kana: Optional[str]
    address: Optional[str]
    phone_number: Optional[str]
    birth_date: Optional[datetime]
    status: int
    tos_accepted_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class IdentityVerificationCreate(BaseModel):
    user_id: UUID


class IdentityVerificationOut(BaseModel):
    id: UUID
    user_id: UUID
    status: int
    checked_at: Optional[datetime]
    notes: Optional[str]

    class Config:
        from_attributes = True


class IdentityDocumentCreate(BaseModel):
    verification_id: UUID
    kind: int
    storage_key: str


class IdentityDocumentOut(BaseModel):
    id: UUID
    verification_id: UUID
    kind: int
    storage_key: str
    created_at: datetime

    class Config:
        from_attributes = True


class CreatorPlatformFeeUpdateRequest(BaseModel):
    creator_id: str
    platform_fee: int = Field(
        ..., ge=0, le=10, description="プラットフォーム手数料（0-10%）"
    )
