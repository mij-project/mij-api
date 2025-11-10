from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Dict
from uuid import UUID
from datetime import datetime
from decimal import Decimal

class CreateSampleRequest(BaseModel):
    temp_video_id: str
    start_time: float  # 秒
    end_time: float    # 秒

class TempVideoResponse(BaseModel):
    temp_video_id: str
    temp_video_url: str
    duration: Optional[float] = None

class SampleVideoResponse(BaseModel):
    sample_video_url: str
    duration: float