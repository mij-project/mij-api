from pydantic import BaseModel, Field
from typing import Optional, Literal
from uuid import UUID
from datetime import datetime

ImageType = Literal[1, 2]  # 1=avatar, 2=cover
SubmissionStatus = Literal[1, 2, 3]  # 1=pending, 2=approved, 3=rejected

class ProfileImageSubmissionCreate(BaseModel):
    """画像申請作成リクエスト"""
    image_type: ImageType = Field(..., description="1=avatar, 2=cover")
    storage_key: str = Field(..., description="S3ストレージキー")

class ProfileImageSubmissionResponse(BaseModel):
    """画像申請レスポンス"""
    id: UUID
    user_id: UUID
    image_type: int
    storage_key: str
    status: int
    approved_by: Optional[UUID] = None
    checked_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ProfileImageSubmissionDetail(BaseModel):
    """画像申請詳細（管理者向け）"""
    id: UUID
    user_id: UUID
    user_email: str
    username: Optional[str] = None
    profile_name: Optional[str] = None
    image_type: int
    image_type_label: str  # "アバター" or "カバー"
    storage_key: str
    image_url: str  # CDN URL
    status: int
    status_label: str  # "申請中" or "承認済み" or "却下"
    approved_by: Optional[UUID] = None
    approver_email: Optional[str] = None
    checked_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class ProfileImageSubmissionListResponse(BaseModel):
    """画像申請一覧レスポンス"""
    items: list[ProfileImageSubmissionDetail]
    total: int
    page: int
    limit: int
    total_pages: int

class ProfileImageApprovalRequest(BaseModel):
    """画像承認リクエスト"""
    pass  # 承認時は追加データ不要

class ProfileImageRejectionRequest(BaseModel):
    """画像却下リクエスト"""
    rejection_reason: str = Field(..., min_length=1, max_length=500, description="却下理由")

class ProfileImageStatusResponse(BaseModel):
    """申請状況レスポンス（ユーザー向け）"""
    avatar_submission: Optional[ProfileImageSubmissionResponse] = None
    cover_submission: Optional[ProfileImageSubmissionResponse] = None
