from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional, List


# --- 検索結果スキーマ ---

class RecentPostThumbnail(BaseModel):
    id: UUID
    thumbnail_url: Optional[str] = None

    class Config:
        from_attributes = True


class CreatorSearchResult(BaseModel):
    id: UUID
    profile_name: str
    username: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    followers_count: Optional[int] = None
    is_verified: Optional[bool] = None
    posts_count: Optional[int] = None
    recent_posts: Optional[List[RecentPostThumbnail]] = []

    class Config:
        from_attributes = True


class PostCreatorInfo(BaseModel):
    id: UUID
    profile_name: str
    username: str
    avatar_url: Optional[str]


class PostSearchResult(BaseModel):
    id: UUID
    description: Optional[str]
    post_type: int
    visibility: int
    likes_count: int
    thumbnail_key: Optional[str] = None
    video_duration: Optional[int] = None
    creator: PostCreatorInfo
    created_at: str

    class Config:
        from_attributes = True


class HashtagSearchResult(BaseModel):
    id: UUID
    name: str
    slug: str
    posts_count: int

    class Config:
        from_attributes = True


class SearchSectionResponse(BaseModel):
    total: int
    items: List
    has_more: bool


class SearchResponse(BaseModel):
    query: str
    total_results: int
    creators: Optional[SearchSectionResponse] = None
    posts: Optional[SearchSectionResponse] = None
    hashtags: Optional[SearchSectionResponse] = None
    search_history_saved: bool = False


# --- 検索履歴スキーマ ---

class SearchHistoryItem(BaseModel):
    id: UUID
    query: str
    search_type: Optional[str]
    filters: Optional[dict]
    created_at: str

    class Config:
        from_attributes = True


class SearchHistoryResponse(BaseModel):
    items: List[SearchHistoryItem]
