from pydantic import BaseModel
from typing import List, Optional

class CategoryResponse(BaseModel):
    id: str
    name: str
    slug: str
    post_count: int

class PostCreatorResponse(BaseModel):
    name: str
    username: str
    avatar_url: Optional[str] = None
    verified: bool
    official: bool

class RankingPostResponse(BaseModel):
    id: str
    is_time_sale: Optional[bool] = False
    post_type: int
    title: str
    thumbnail: Optional[str] = None
    likes: int
    duration: Optional[str] = None
    rank: int
    creator: PostCreatorResponse


class CreatorResponse(BaseModel):
    id: str
    name: str
    username: str
    avatar: Optional[str] = None
    followers: int
    rank: Optional[int] = None
    follower_ids: Optional[List[str]] = None
    likes: Optional[int] = None
    official: bool
    
class RecentPostResponse(BaseModel):
    id: str
    is_time_sale: Optional[bool] = False
    post_type: int
    title: str
    thumbnail: Optional[str] = None
    likes: int
    duration: Optional[str] = None
    creator: PostCreatorResponse

class TopPageResponse(BaseModel):
    categories: List[CategoryResponse]
    ranking_posts: List[RankingPostResponse]
    top_creators: List[CreatorResponse]
    new_creators: List[CreatorResponse]
    recent_posts: List[RecentPostResponse]
