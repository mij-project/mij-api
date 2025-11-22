from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Dict
from uuid import UUID
from datetime import datetime
from decimal import Decimal

class CreateSampleRequest(BaseModel):
    temp_video_id: str
    start_time: float  # 秒
    end_time: float    # 秒

class TempVideoMultipartInitResponse(BaseModel):
    s3_key: str
    bucket: str
    upload_id: str
    expires_in: int

class SampleVideoResponse(BaseModel):
    sample_video_url: str
    duration: float

class TempVideoPartPresignResponse(BaseModel):
    s3_key: str
    upload_id: str
    part_number: int
    upload_url: str
    expires_in: int

class CompletedPart(BaseModel):
    part_number: int
    etag: str  # フロントで各PUTレスポンスのETagを取ってもらう

class TempVideoMultipartCompleteRequest(BaseModel):
    s3_key: str
    upload_id: str
    parts: list[CompletedPart]


class BulkPartPresignRequest(BaseModel):
    """一括Presigned URL取得リクエスト"""
    s3_key: str
    upload_id: str
    part_numbers: List[int]  # アップロードするパート番号のリスト


class PartPresignUrl(BaseModel):
    """個別パートのPresigned URL"""
    part_number: int
    upload_url: str


class BulkPartPresignResponse(BaseModel):
    """一括Presigned URL取得レスポンス"""
    s3_key: str
    upload_id: str
    urls: List[PartPresignUrl]
    expires_in: int
