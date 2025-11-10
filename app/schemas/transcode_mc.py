from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Dict
from uuid import UUID
from datetime import datetime
from decimal import Decimal


class TranscodeMCUpdateRequest(BaseModel):
    post_id: str
    media_assets: List[str]  # メディアアセットIDのリスト（文字列形式）
    post_type: int