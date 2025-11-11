from pydantic import BaseModel 
from typing import Optional, List

# For rankinng overall
class RankingPostsAllTimeResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    likes_count: int
    creator_name: str
    username: str
    creator_avatar_url: Optional[str] = None
    rank: int

class RankingPostsMonthlyResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    likes_count: int
    creator_name: str
    username: str
    creator_avatar_url: Optional[str] = None
    rank: int

class RankingPostsWeeklyResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    likes_count: int
    creator_name: str
    username: str
    creator_avatar_url: Optional[str] = None
    rank: int

class RankingPostsDailyResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    likes_count: int
    creator_name: str
    username: str
    creator_avatar_url: Optional[str] = None
    rank: int

class RankingOverallResponse(BaseModel):
    all_time: List[RankingPostsAllTimeResponse]
    monthly: List[RankingPostsMonthlyResponse]
    weekly: List[RankingPostsWeeklyResponse]
    daily: List[RankingPostsDailyResponse]

# For ranking by genres

class RankingPostsGenresDetailResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    likes_count: int
    creator_name: str
    username: str
    creator_avatar_url: Optional[str] = None
    rank: int

class RankingPostsGenresResponse(BaseModel):
    genre_id: str
    genre_name: str
    posts: List[RankingPostsGenresDetailResponse]

class RankingGenresResponse(BaseModel):
    all_time: List [RankingPostsGenresResponse]
    monthly: List [RankingPostsGenresResponse]
    weekly: List [RankingPostsGenresResponse]
    daily: List [RankingPostsGenresResponse]

# For ranking by genres detail
class RankingPostsDetailDailyResponse(BaseModel):
    id: str
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    likes_count: int
    creator_name: Optional[str] = None
    username: Optional[str] = None
    creator_avatar_url: Optional[str] = None
    rank: int

class RankingPostsDetailResponse(BaseModel):
    posts: List[RankingPostsDetailDailyResponse]
    next_page: int | None = None
    previous_page: int | None = None
    has_next: bool = False
    has_previous: bool = False


class RankingCreators(BaseModel):
    id: str
    name: str
    username: str
    avatar: Optional[str] = None
    cover: Optional[str] = None
    followers: int
    likes: int
    rank: int
    follower_ids: List[str] | List

class RankingCreatorsResponse(BaseModel):
    all_time: List [RankingCreators]
    monthly: List [RankingCreators]
    weekly: List [RankingCreators]
    daily: List [RankingCreators]

class RankingCreatorsDetailResponse(BaseModel):
    creators: List[RankingCreators]
    next_page: int | None = None
    previous_page: int | None = None
    has_next: bool = False
    has_previous: bool = False
    