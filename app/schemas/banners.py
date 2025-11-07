from pydantic import BaseModel, Field, validator, field_validator
from typing import Optional, Literal, List, Any, Union
from uuid import UUID
from datetime import datetime
from fastapi import UploadFile

BannerType = Literal[1, 2]  # 1=クリエイター, 2=イベント
BannerStatus = Literal[0, 1, 2]  # 0=無効, 1=有効, 2=下書き


class BannerCreateRequest(BaseModel):
    """バナー作成リクエスト"""
    type: BannerType = Field(..., description="1=クリエイター, 2=イベント")
    title: str = Field(..., min_length=1, max_length=100, description="バナータイトル")
    alt_text: str = Field(..., min_length=1, max_length=200, description="画像の代替テキスト")
    cta_label: str = Field(default="", max_length=50, description="CTAラベル")
    creator_id: Optional[UUID] = Field(None, description="クリエイターID (type=1の場合必須)")
    external_url: Optional[str] = Field(None, max_length=500, description="外部URL (type=2の場合必須)")
    status: BannerStatus = Field(default=2, description="0=無効, 1=有効, 2=下書き")
    start_at: Optional[datetime] = Field(None, description="表示開始日時")
    end_at: Optional[datetime] = Field(None, description="表示終了日時")
    display_order: int = Field(default=100, ge=0, description="表示順序")
    priority: int = Field(default=0, ge=0, description="優先度")
    image: Optional[Union[UploadFile, dict[str, Any]]] = Field(None, description="バナー画像")

    @field_validator('creator_id')
    @classmethod
    def validate_creator_id(cls, v, info):
        """type=1の場合、creator_idは必須"""
        if info.data.get('type') == 1 and v is None:
            raise ValueError('type=1の場合、creator_idは必須です')
        return v

    @field_validator('external_url')
    @classmethod
    def validate_external_url(cls, v, info):
        """type=2の場合、external_urlは必須"""
        if info.data.get('type') == 2 and not v:
            raise ValueError('type=2の場合、external_urlは必須です')
        return v

    @field_validator('end_at')
    @classmethod
    def validate_dates(cls, v, info):
        """end_atはstart_at以降である必要がある"""
        start_at = info.data.get('start_at')
        if start_at and v and v < start_at:
            raise ValueError('end_atはstart_at以降である必要があります')
        return v

    @field_validator('image', mode='before')
    @classmethod
    def normalize_image(cls, v):
        """空オブジェクトや空文字は None とみなす"""
        if v in (None, ""):
            return None
        if isinstance(v, dict) and not v:
            return None
        return v


class BannerUpdateRequest(BaseModel):
    """バナー更新リクエスト"""
    type: Optional[BannerType] = Field(None, description="1=クリエイター, 2=イベント")
    title: Optional[str] = Field(None, min_length=1, max_length=100, description="バナータイトル")
    alt_text: Optional[str] = Field(None, min_length=1, max_length=200, description="画像の代替テキスト")
    cta_label: Optional[str] = Field(None, max_length=50, description="CTAラベル")
    creator_id: Optional[UUID] = Field(None, description="クリエイターID")
    external_url: Optional[str] = Field(None, max_length=500, description="外部URL")
    status: Optional[BannerStatus] = Field(None, description="0=無効, 1=有効, 2=下書き")
    start_at: Optional[datetime] = Field(None, description="表示開始日時")
    end_at: Optional[datetime] = Field(None, description="表示終了日時")
    display_order: Optional[int] = Field(None, ge=0, description="表示順序")
    priority: Optional[int] = Field(None, ge=0, description="優先度")


class BannerImageUpdateRequest(BaseModel):
    """バナー画像更新リクエスト（画像差し替え用）"""
    image_key: str = Field(..., description="新しいS3保存先キー")


class BannerReorderRequest(BaseModel):
    """バナー並び替えリクエスト"""
    banner_ids: List[UUID] = Field(..., min_length=1, description="バナーIDリスト（並び順）")


class BannerResponse(BaseModel):
    """バナー基本レスポンス（顧客向け）"""
    id: str
    type: int
    title: str
    image_url: Optional[str] = None
    avatar_url: Optional[str] = None
    image_source: Optional[int] = None
    alt_text: str
    creator_id: Optional[str] = None
    creator_username: Optional[str] = None
    creator_profile_name: Optional[str] = None
    external_url: Optional[str] = None
    display_order: int


class BannerDetail(BaseModel):
    """バナー詳細レスポンス（管理画面向け）"""
    id: str
    type: int
    type_label: str  # "クリエイター" or "イベント"
    title: str
    image_key: Optional[str] = None
    image_url: Optional[str] = None
    alt_text: Optional[str] = None
    cta_label: Optional[str] = None
    creator_id: Optional[str] = None
    creator_username: Optional[str] = None
    creator_profile_name: Optional[str] = None
    creator_avatar_url: Optional[str] = None
    external_url: Optional[str] = None
    status: int
    status_label: str  # "無効" or "有効" or "下書き"
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    display_order: int
    priority: Optional[int] = None
    image_source: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class BannerListResponse(BaseModel):
    """バナー一覧レスポンス"""
    items: List[BannerDetail]
    total: int
    page: int
    limit: int
    total_pages: int


class ActiveBannersResponse(BaseModel):
    """有効なバナー一覧レスポンス（顧客向け）"""
    banners: List[BannerResponse]
