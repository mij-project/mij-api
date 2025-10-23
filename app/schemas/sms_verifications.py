from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

class SMSVerificationRequest(BaseModel):
    phone_e164: str
    purpose: int

class SMSVerificationVerifyRequest(BaseModel):
    phone_e164: str
    code: str
    purpose: int

class SMSVerificationResponse(BaseModel):
    phone_e164: str
    code: str
    purpose: str = "login"