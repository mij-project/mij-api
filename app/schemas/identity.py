from pydantic import BaseModel, Field
from typing import Dict, List, Literal
from uuid import UUID
from app.schemas.commons import PresignResponseItem

Kind = Literal["front", "back", "selfie"]

class VerifyPresignResponse(BaseModel):
    verification_id: UUID
    uploads: dict[str, PresignResponseItem]

class CompleteRequest(BaseModel):
    submission_id: str
    files: List[dict]

class VerifyFileSpec(BaseModel):
    kind: Kind
    ext: Literal["jpg","jpeg","png","webp"]
    content_type: str | None = None


class VerifyRequest(BaseModel):
    verification_id: str
    files: List[VerifyFileSpec]

class VerifyPresignRequest(BaseModel):
    files: List[VerifyFileSpec] = Field(..., description='例: [{"kind":"front","content_type":"image/jpeg","ext":"jpg"}, ...]')