from typing import Optional
from pydantic import BaseModel, Field

class ProfileViewTrackingPayload(BaseModel):
    profile_user_id: str = Field(..., description="プロフィールユーザーID")

class PostViewTrackingPayload(BaseModel):
    post_id: str = Field(..., description="投稿ID")
    watched_duration_sec: Optional[float] = Field(None, description="視聴時間（秒）")
    video_duration_sec: Optional[float] = Field(None, description="動画時間（秒）")
    user_id: Optional[str] = Field(None, description="ユーザーID")
