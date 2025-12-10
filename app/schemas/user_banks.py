from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class UserDefaultBank(BaseModel):
    id: str
    account_number: str
    account_holder_name: str
    account_holder_name_kana: Optional[str] = None
    account_type: int
    account_number: str
    bank_code: str
    bank_name: str
    bank_name_kana: str

    branch_code: str
    branch_name: str
    branch_name_kana: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserDefaultBankResponse(BaseModel):
    user_bank: Optional[UserDefaultBank] = None


class ExternalBank(BaseModel):
    businessType: str
    businessTypeCode: str
    code: str
    fullWidthKana: str
    halfWidthKana: str
    hiragana: str
    name: str


class ExternalBranch(BaseModel):
    code: str
    name: str
    halfWidthKana: str
    fullWidthKana: str
    hiragana: str


class UserDefaultBankSettingRequest(BaseModel):
    account_type: int
    account_number: str
    account_holder: str
    bank: ExternalBank
    branch: ExternalBranch
