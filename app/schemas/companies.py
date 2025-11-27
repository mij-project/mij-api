from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal
from uuid import UUID
from datetime import datetime

CompanyType = Literal["primary", "secondary"]  # primary=1次代理店, secondary=2次代理店


class CompanyCreateRequest(BaseModel):
    """企業作成リクエスト"""
    name: str = Field(..., min_length=1, max_length=200, description="企業名")
    parent_company_id: Optional[UUID] = Field(None, description="親企業ID (2次代理店の場合)")

    @field_validator('parent_company_id')
    @classmethod
    def validate_parent_company_id(cls, v):
        """parent_company_idが存在する場合、有効なUUIDであること"""
        if v is not None and not isinstance(v, UUID):
            raise ValueError('parent_company_idは有効なUUIDである必要があります')
        return v


class CompanyUpdateRequest(BaseModel):
    """企業更新リクエスト"""
    name: Optional[str] = Field(None, min_length=1, max_length=200, description="企業名")
    parent_company_id: Optional[UUID] = Field(None, description="親企業ID")


class UserBasicInfo(BaseModel):
    """ユーザー基本情報"""
    id: str
    email: str
    username: Optional[str] = None
    profile_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: Optional[int] = None


class CompanyDetail(BaseModel):
    """企業詳細レスポンス"""
    id: str
    name: str
    parent_company_id: Optional[str] = None
    parent_company_name: Optional[str] = None
    code: str
    type: CompanyType  # "primary" or "secondary"
    user_count: int = 0
    child_count: int = 0
    created_at: datetime
    updated_at: datetime


class CompanyListResponse(BaseModel):
    """企業一覧レスポンス"""
    items: List[CompanyDetail]
    total: int
    page: int
    limit: int
    total_pages: int


class CompanyBasicInfo(BaseModel):
    """企業基本情報（選択用）"""
    id: str
    name: str
    code: str
    fee_percent: Optional[int] = None
    exists: Optional[bool] = None


class CompanyUserCreateRequest(BaseModel):
    """企業ユーザー追加リクエスト"""
    user_id: UUID = Field(..., description="ユーザーID")
    company_fee_percent: int = Field(default=3, ge=0, le=100, description="企業への支払い率（0-100%）")
    is_referrer: bool = Field(default=True, description="紹介者フラグ")


class CompanyUserUpdateRequest(BaseModel):
    """企業ユーザー支払い率更新リクエスト"""
    company_fee_percent: int = Field(..., ge=0, le=100, description="企業への支払い率（0-100%）")


class CompanyUserDetail(BaseModel):
    """企業ユーザー詳細レスポンス"""
    id: str
    company_id: str
    user_id: str
    user: UserBasicInfo
    company_fee_percent: int
    is_referrer: bool
    referrer_company_id: Optional[str] = None
    referrer_company: Optional[CompanyBasicInfo] = None
    parent_company_id: Optional[str] = None
    parent_company: Optional[CompanyBasicInfo] = None
    created_at: datetime
    updated_at: datetime


class CompanyUserListResponse(BaseModel):
    """企業ユーザー一覧レスポンス"""
    items: List[CompanyUserDetail]
    total: int
    page: int
    limit: int
    total_pages: int
