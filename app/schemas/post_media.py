from pydantic import BaseModel, Field
from typing import Literal, List, Union
from app.schemas.commons import PresignResponseItem
from uuid import UUID
from typing import Optional

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
    sample_type: Optional[str] = Field(None, description='サンプル動画の種類: upload=アップロード, cut_out=本編から指定')
    sample_start_time: Optional[float] = Field(None, description='本編から指定の場合の開始時間（秒）')
    sample_end_time: Optional[float] = Field(None, description='本編から指定の場合の終了時間（秒）')

class UpdateMediaVideoFileSpec(BaseModel):
    post_id: UUID = Field(..., description='投稿ID')
    kind: VideoKind
    orientation: Orientation
    content_type: Literal["video/mp4", "video/webm", "video/quicktime"]
    ext: Literal["mp4", "webm", "mov"]
    sample_type: Optional[str] = Field(None, description='サンプル動画の種類: upload=アップロード, cut_out=本編から指定')
    sample_start_time: Optional[float] = Field(None, description='本編から指定の場合の開始時間（秒）')
    sample_end_time: Optional[float] = Field(None, description='本編から指定の場合の終了時間（秒）')

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

class TriggerBatchProcessRequest(BaseModel):
    """バッチ処理トリガーリクエスト"""
    post_id: UUID = Field(..., description='投稿ID')
    tmp_storage_key: str = Field(..., description='tmpバケットのストレージキー (TEMP_VIDEO_DESTINATION)')
    need_trim: bool = Field(False, description='FFmpegでトリミングが必要か (NEED_TRIM)')
    start_time: Optional[float] = Field(None, description='トリミング開始時間（秒）(START_TIME)')
    end_time: Optional[float] = Field(None, description='トリミング終了時間（秒）(END_TIME)')
    main_orientation: Optional[Orientation] = Field(None, description='メイン動画の向き (MAIN_ORIENTATION)')
    sample_orientation: Optional[Orientation] = Field(None, description='サンプル動画の向き (SAMPLE_ORIENTATION)')
    content_type: Optional[str] = Field(None, description='コンテンツタイプ (CONTENT_TYPE)')

class TriggerBatchProcessResponse(BaseModel):
    """バッチ処理トリガーレスポンス"""
    status: str = Field(..., description='処理状態（processing）')
    message: str = Field(..., description='メッセージ')
    tmp_storage_key: str = Field(..., description='tmpバケットのストレージキー')