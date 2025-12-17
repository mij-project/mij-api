from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class AdvertisingAgencyCreateRequest(BaseModel):
    """広告会社作成リクエスト"""
    name: str = Field(..., min_length=1, max_length=200, description="会社名")
    status: int = Field(default=1, ge=1, le=2, description="ステータス: 1=有効, 2=停止")


class AdvertisingAgencyUpdateRequest(BaseModel):
    """広告会社更新リクエスト"""
    name: Optional[str] = Field(None, min_length=1, max_length=200, description="会社名")
    status: Optional[int] = Field(None, ge=1, le=2, description="ステータス: 1=有効, 2=停止")


class AdvertisingAgencyDetail(BaseModel):
    """広告会社詳細レスポンス"""
    id: str
    name: str
    code: str
    referral_url: Optional[str] = None
    status: int
    status_label: str
    user_count: int = 0
    access_count: int = 0
    created_at: datetime
    updated_at: datetime


class AdvertisingAgencyListResponse(BaseModel):
    """広告会社一覧レスポンス"""
    items: List[AdvertisingAgencyDetail]
    total: int
    page: int
    limit: int
    total_pages: int


class ReferredUserDetail(BaseModel):
    """紹介ユーザー詳細レスポンス"""
    user_id: str
    username: Optional[str] = None
    profile_name: Optional[str] = None
    avatar_url: Optional[str] = None
    email: Optional[str] = None
    referral_code: str
    registration_source: Optional[str] = None
    referred_at: datetime


class ReferredUserListResponse(BaseModel):
    """紹介ユーザー一覧レスポンス"""
    items: List[ReferredUserDetail]
    total: int
    page: int
    limit: int
    total_pages: int
