from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal, List
from uuid import UUID
from datetime import datetime
from app.constants.enums import EventStatus
EventStatus = Literal[0, 1, 2]  # 0=無効, 1=有効, 2=下書き


class EventCreateRequest(BaseModel):
    """イベント作成リクエスト"""
    code: str = Field(..., min_length=1, max_length=100, description="イベントコード(一意)")
    name: str = Field(..., min_length=1, max_length=200, description="イベント名")
    description: Optional[str] = Field(None, max_length=5000, description="イベント説明")
    status: EventStatus = Field(default=2, description="0=無効, 1=有効, 2=下書き")
    start_date: Optional[datetime] = Field(None, description="開始日時")
    end_date: Optional[datetime] = Field(None, description="終了日時")

    @field_validator('end_date')
    @classmethod
    def validate_dates(cls, v, info):
        """end_dateはstart_date以降である必要がある"""
        start_date = info.data.get('start_date')
        if start_date and v and v < start_date:
            raise ValueError('end_dateはstart_date以降である必要があります')
        return v


class EventUpdateRequest(BaseModel):
    """イベント更新リクエスト"""
    code: Optional[str] = Field(None, min_length=1, max_length=100, description="イベントコード(一意)")
    name: Optional[str] = Field(None, min_length=1, max_length=200, description="イベント名")
    description: Optional[str] = Field(None, max_length=5000, description="イベント説明")
    status: Optional[EventStatus] = Field(None, description="0=無効, 1=有効, 2=下書き")
    start_date: Optional[datetime] = Field(None, description="開始日時")
    end_date: Optional[datetime] = Field(None, description="終了日時")

    @field_validator('end_date')
    @classmethod
    def validate_dates(cls, v, info):
        """end_dateはstart_date以降である必要がある"""
        start_date = info.data.get('start_date')
        if start_date and v and v < start_date:
            raise ValueError('end_dateはstart_date以降である必要があります')
        return v


class EventDetail(BaseModel):
    """イベント詳細レスポンス"""
    id: str
    code: str
    name: Optional[str] = None
    description: Optional[str] = None
    status: int
    status_label: str  # "無効" or "有効" or "下書き"
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    participant_count: int = 0  # 参加者数
    created_at: datetime
    updated_at: datetime


class EventListResponse(BaseModel):
    """イベント一覧レスポンス"""
    items: List[EventDetail]
    total: int
    page: int
    limit: int
    total_pages: int


class EventParticipantDetail(BaseModel):
    """イベント参加者詳細"""
    user_id: str
    username: Optional[str] = None
    profile_name: Optional[str] = None
    avatar_url: Optional[str] = None
    participated_at: datetime  # 参加日時


class EventParticipantListResponse(BaseModel):
    """イベント参加者一覧レスポンス"""
    items: List[EventParticipantDetail]
    total: int
    page: int
    limit: int
    total_pages: int
