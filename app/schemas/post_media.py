from pydantic import BaseModel, Field
from typing import Literal, List, Union
from app.schemas.commons import PresignResponseItem
from uuid import UUID

ImageKind = Literal["ogp", "thumbnail", "images"]
VideoKind = Literal["main", "sample"]
Orientation = Literal["portrait", "landscape", "square"]

class PostMediaImageFileSpec(BaseModel):
    post_id: UUID = Field(..., description='投稿ID')
    kind: ImageKind
    orientation: Orientation
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    ext: Literal["mp4", "jpg", "jpeg", "png", "webp"]

class UpdateMediaImageFileSpec(BaseModel):
    kind: ImageKind
    orientation: Orientation
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    ext: Literal["mp4", "jpg", "jpeg", "png", "webp"]

class PostMediaVideoFileSpec(BaseModel):
    post_id: UUID = Field(..., description='投稿ID')
    kind: VideoKind
    orientation: Orientation
    content_type: Literal["video/mp4", "video/webm", "video/quicktime"]
    ext: Literal["mp4", "webm", "mov"]

class UpdateMediaVideoFileSpec(BaseModel):
    post_id: UUID = Field(..., description='投稿ID')
    kind: VideoKind
    orientation: Orientation
    content_type: Literal["video/mp4", "video/webm", "video/quicktime"]
    ext: Literal["mp4", "webm", "mov"]

class PostMediaImagePresignRequest(BaseModel):
    files: List[PostMediaImageFileSpec] = Field(..., description='例: [{"kind":"ogp","ext":"jpg"}, ...]')

class UpdateMediaImagePresignRequest(BaseModel):
    post_id: UUID = Field(..., description='投稿ID')
    files: List[PostMediaImageFileSpec] = Field(..., description='例: [{"kind":"ogp","ext":"jpg"}, ...]')

class PostMediaVideoPresignRequest(BaseModel):
    files: List[PostMediaVideoFileSpec] = Field(..., description='例: [{"kind":"main","ext":"mp4"}, ...]')

class UpdateMediaVideoPresignRequest(BaseModel):
    post_id: UUID = Field(..., description='投稿ID')   
    files: List[UpdateMediaVideoFileSpec] = Field(..., description='例: [{"kind":"main","ext":"mp4"}, ...]')

class PostMediaImagePresignResponse(BaseModel):
    uploads: dict[str, Union[PresignResponseItem, List[PresignResponseItem]]]

class PostMediaVideoPresignResponse(BaseModel):
    uploads: dict[str, PresignResponseItem]

class PostRequest(BaseModel):
    title: str
    category_ids: List[str]
    
class PoseMediaCovertRequest(BaseModel):
    post_id: UUID

class UpdateImagesPresignRequest(BaseModel):
    """画像投稿の更新用リクエスト（複数画像の追加/削除対応）"""
    post_id: UUID = Field(..., description='投稿ID')
    add_images: List[UpdateMediaImageFileSpec] = Field(default=[], description='追加する画像のリスト')
    delete_image_ids: List[str] = Field(default=[], description='削除する画像のmedia_assets.id一覧')

class UpdateImagesPresignResponse(BaseModel):
    """画像投稿の更新用レスポンス"""
    uploads: List[PresignResponseItem] = Field(default=[], description='アップロードURL一覧')