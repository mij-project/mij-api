from pydantic import BaseModel 
from typing import Optional, List

# For rankinng overall
class RankingPostsAllTimeResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    likes_count: int
    creator_name: str
    official: bool
    username: str
    creator_avatar_url: Optional[str] = None
    rank: int
    duration: Optional[str] = None

class RankingPostsMonthlyResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    likes_count: int
    creator_name: str
    official: bool
    username: str
    creator_avatar_url: Optional[str] = None
    rank: int
    duration: Optional[str] = None

class RankingPostsWeeklyResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    likes_count: int
    creator_name: str
    official: bool
    username: str
    creator_avatar_url: Optional[str] = None
    rank: int
    duration: Optional[str] = None
    
class RankingPostsDailyResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    likes_count: int
    creator_name: str
    official: bool
    username: str
    creator_avatar_url: Optional[str] = None
    rank: int
    duration: Optional[str] = None
class RankingOverallResponse(BaseModel):
    all_time: List[RankingPostsAllTimeResponse]
    monthly: List[RankingPostsMonthlyResponse]
    weekly: List[RankingPostsWeeklyResponse]
    daily: List[RankingPostsDailyResponse]

# For ranking by genres

class RankingPostsCategoriesDetailResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    likes_count: int
    creator_name: str
    official: bool
    username: str
    creator_avatar_url: Optional[str] = None
    rank: int
    duration: Optional[str] = None  

class RankingPostsCategoriesResponse(BaseModel):
    category_id: str
    category_name: str
    posts: List[RankingPostsCategoriesDetailResponse]

class RankingCategoriesResponse(BaseModel):
    all_time: List [RankingPostsCategoriesResponse]
    monthly: List [RankingPostsCategoriesResponse]
    weekly: List [RankingPostsCategoriesResponse]
    daily: List [RankingPostsCategoriesResponse]

# For ranking by genres detail
class RankingPostsDetailDailyResponse(BaseModel):
    id: str
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    likes_count: int
    official: bool
    creator_name: Optional[str] = None
    username: Optional[str] = None
    creator_avatar_url: Optional[str] = None
    rank: int
    duration: Optional[str] = None

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
    official: bool
    
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

class RankingCreatorsCategories(BaseModel):
    category_id: str
    category_name: str
    creators: List[RankingCreators]

class RankingCreatorsCategoriesResponse(BaseModel):
    all_time: List [RankingCreatorsCategories]
    monthly: List [RankingCreatorsCategories]
    weekly: List [RankingCreatorsCategories]
    daily: List [RankingCreatorsCategories]