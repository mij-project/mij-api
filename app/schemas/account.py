from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Dict
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from app.schemas.commons import PresignResponseItem
from app.schemas.purchases import SinglePurchaseResponse
from app.models.posts import Posts
from app.schemas.message_asset import UserMessageAssetsListResponse

Kind = Literal["avatar", "cover"]

class AccountFileSpec(BaseModel):
    kind: Kind
    content_type: Literal["image/jpeg","image/png","image/webp"]
    ext: Literal["jpg","jpeg","png","webp"]

class LikedPostResponse(BaseModel):
    id: UUID
    description: str
    creator_user_id: UUID
    profile_name: str
    username: str
    avatar_url: Optional[str] = None
    thumbnail_key: Optional[str] = None
    duration_sec: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime
    is_time_sale: Optional[bool] = None
    class Config:
        from_attributes = True

class ProfileInfo(BaseModel):
    profile_name: str
    username: str
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None

class ProfileEditInfo(BaseModel):
    """プロフィール編集用の情報"""
    profile_name: str
    username: str
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    bio: Optional[str] = None
    links: Optional[dict] = None

class SocialInfo(BaseModel):
    followers_count: int
    following_count: int
    total_likes: int
    liked_posts: List[LikedPostResponse] = []

class PostsInfo(BaseModel):
    pending_posts_count: int
    rejected_posts_count: int
    unpublished_posts_count: int
    deleted_posts_count: int
    approved_posts_count: int
    reserved_posts_count: int

class SalesInfo(BaseModel):
    total_sales: int

class SubscribedPlanDetail(BaseModel):
    purchase_id: str
    plan_id: str
    plan_name: str
    plan_description: Optional[str] = None
    price: int
    purchase_created_at: datetime
    next_billing_date: Optional[datetime] = None
    status: int
    creator_avatar_url: Optional[str] = None
    creator_username: Optional[str] = None
    creator_profile_name: Optional[str] = None
    post_count: int
    thumbnail_keys: List[str] = []

class PlanInfo(BaseModel):
    plan_count: int
    total_price: int
    subscribed_plan_count: int
    subscribed_total_price: int
    subscribed_plan_details: List[SubscribedPlanDetail] = []
    single_purchases_count: int
    single_purchases_data: List[SinglePurchaseResponse] = []

class PlansSubscribedInfo(BaseModel):
    plan_count: int
    total_price: int
    subscribed_plan_count: int
    subscribed_total_price: int
    subscribed_plan_names: List[str] = []
    subscribed_plan_details: List[SubscribedPlanDetail] = []

class AccountInfoResponse(BaseModel):
    profile_info: ProfileInfo
    social_info: SocialInfo
    posts_info: PostsInfo
    sales_info: SalesInfo
    plan_info: PlanInfo
    message_assets_info: UserMessageAssetsListResponse

class AvatarPresignRequest(BaseModel):
    files: List[AccountFileSpec] = Field(..., description='例: [{"kind":"avatar","ext":"jpg"}, ...]')

class AccountPresignResponse(BaseModel):
    uploads: dict[str, PresignResponseItem]

class AccountUpdateRequest(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    description: Optional[str] = None
    links: Optional[dict] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None

class AccountUpdateResponse(BaseModel):
    message: str
    success: bool

class PostCardResponse(BaseModel):
    id: UUID
    thumbnail_url: Optional[str] = None
    title: str
    creator_avatar: Optional[str] = None
    creator_name: str
    creator_username: str
    official: bool
    likes_count: int
    comments_count: int
    duration: Optional[str] = None
    is_video: bool
    created_at: datetime
    price: Optional[int] = None
    currency: Optional[str] = None
    plan_name: Optional[str] = None  # プラン名（プラン購読の場合のみ）
    price_id: Optional[str] = None
    sale_percentage: Optional[int] = None
    end_date: Optional[datetime] = None
    is_time_sale: Optional[bool] = False

    class Config:
        from_attributes = True

class BookmarkedPostsResponse(BaseModel):
    bookmarks: List[PostCardResponse]

class LikedPostsListResponse(BaseModel):
    liked_posts: List[PostCardResponse]

class BoughtPostsResponse(BaseModel):
    bought_posts: List[PostCardResponse]

class AccountPostResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    likes_count: int
    comments_count: int = 0
    purchase_count: int = 0
    creator_name: str
    username: str
    creator_avatar_url: Optional[str] = None
    price: int
    currency: str
    created_at: Optional[str] = None
    duration: Optional[str] = None
    is_video: bool = False
    has_plan: bool = False

class AccountPostStatusResponse(BaseModel):
    pending_posts: List[AccountPostResponse] = []
    rejected_posts: List[AccountPostResponse] = []
    unpublished_posts: List[AccountPostResponse] = []
    deleted_posts: List[AccountPostResponse] = []
    approved_posts: List[AccountPostResponse] = []
    reserved_posts: List[AccountPostResponse] = []

class AccountMediaAsset(BaseModel):
    """クリエイター用投稿詳細のメディアアセット情報"""
    kind: int
    storage_key: Optional[str] = None
    status: int
    reject_comments: Optional[str] = None
    duration_sec: Optional[Decimal] = None
    orientation: Optional[int] = None
    sample_type: Optional[str] = None
    sample_start_time: Optional[Decimal] = None
    sample_end_time: Optional[Decimal] = None


class PlanSummary(BaseModel):
    """投稿に紐づくプランの簡易情報"""
    id: str
    name: Optional[str] = None
    price: Optional[int] = None
    currency: Optional[str] = "JPY"


class AccountPostDetailResponse(BaseModel):
    """クリエイター用投稿詳細レスポンス"""
    id: str
    description: str
    scheduled_at: Optional[str] = None
    expiration_at: Optional[str] = None
    reject_comments: Optional[str] = None
    likes_count: int
    comments_count: int
    purchase_count: int
    creator_name: str
    username: str
    creator_avatar_url: Optional[str] = None
    price: int
    currency: str
    duration: Optional[str] = None
    is_video: bool
    post_type: Optional[int] = None  # 1=VIDEO, 2=IMAGE
    status: int
    visibility: int
    # メディア情報
    media_assets: Dict[str, AccountMediaAsset] = Field(default_factory=dict)
    # カテゴリー・プラン情報
    category_ids: List[str] = Field(default_factory=list)
    tags: Optional[str] = None
    plan_list: List[PlanSummary] = Field(default_factory=list)

class AccountPostUpdateRequest(BaseModel):
    """投稿更新リクエスト"""
    description: Optional[str] = None
    status: Optional[int] = None
    visibility: Optional[int] = None
    scheduled_at: Optional[str] = None

class AccountPostUpdateResponse(BaseModel):
    """投稿更新レスポンス"""
    message: str
    success: bool

class AccountEmailSettingRequest(BaseModel):
    type: int # 1: メールアドレス設定, 2: メールアドレス認証
    email: Optional[str] = None
    token: Optional[str] = None